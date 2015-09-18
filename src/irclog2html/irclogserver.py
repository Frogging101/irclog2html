#!/usr/bin/env python
"""
Serve IRC logs (WSGI app)

Expects to find logs matching the IRCLOG_GLOB pattern (default: *.log)
in the directory specified by the IRCLOG_LOCATION environment variable.
Expects the filenames to contain a ISO 8601 date (YYYY-MM-DD).

Apache configuration example:

  WSGIScriptAlias /irclogs /path/to/irclogserver.py
  <Location /irclogs>
    SetEnv IRCLOG_LOCATION /path/to/irclog/files/
    # Uncomment the following if your log files use a different format
    #SetEnv IRCLOG_GLOB "*.log.????-??-??"
  </Location>

"""

# Copyright (c) 2015, Marius Gedminas and contributors
#
# Released under the terms of the GNU GPL
# http://www.gnu.org/copyleft/gpl.html

import cgi
import io
import os

from .irclog2html import (
    CSS_FILE, LogParser, XHTMLTableStyle, convert_irc_log,
)
from .irclogsearch import (
    DEFAULT_LOGFILE_PATH, DEFAULT_LOGFILE_PATTERN, search_page,
)


def get_path(environ):
    path = environ.get('PATH_INFO', '/')
    path = path[1:]  # Remove the leading slash
    if '/' in path or '\\' in path:
        return None
    return path if path != '' else 'index.html'


def application(environ, start_response):
    """WSGI application"""
    logfile_path = environ.get('IRCLOG_LOCATION') or DEFAULT_LOGFILE_PATH
    logfile_pattern = environ.get('IRCLOG_GLOB') or DEFAULT_LOGFILE_PATTERN
    form = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ)
    stream = io.TextIOWrapper(io.BytesIO(), 'ascii',
                              errors='xmlcharrefreplace',
                              line_buffering=True)

    status = "200 Ok"
    content_type = "text/html; charset=UTF-8"
    headers = {}

    path = get_path(environ)
    if path is None:
        status = "404 Not Found"
        result = [b"Not found"]
        content_type = "text/plain"
    elif path == 'search':
        fmt = search_page(stream, form, logfile_path, logfile_pattern)
        result = [stream.buffer.getvalue()]
        del fmt
    elif path == 'irclog.css':
        content_type = "text/css"
        try:
            with open(CSS_FILE, "rb") as f:
                result = [f.read()]
        except IOError:  # pragma: nocover
            status = "404 Not Found"
            result = [b"Not found"]
            content_type = "text/plain"
    else:
        try:
            with open(os.path.join(logfile_path, path), "rb") as f:
                result = [f.read()]
        except IOError:
            if path == 'index.html':
                # no index? redirect to search page
                status = "302 Found"
                result = [b"Try /search"]
                headers['Location'] = '/search'
                content_type = "text/plain"
            elif path.endswith('.html'):
                buf = io.BytesIO()
                with open(os.path.join(logfile_path, path[:-5]), 'rb') as f:
                    parser = LogParser(f)
                    formatter = XHTMLTableStyle(buf)
                    convert_irc_log(parser, formatter, path[:-5],
                                    ('', ''), ('', ''), ('', ''),
                                    searchbox=True)
                    result = [buf.getvalue()]
            else:
                status = "404 Not Found"
                result = [b"Not found"]
                content_type = "text/plain"
        else:
            if path.endswith('.css'):
                content_type = "text/css"
            elif path.endswith('.log') or path.endswith('.txt'):
                content_type = "text/plain; charset=UTF-8"
                result = [LogParser.decode(line).encode('UTF-8')
                          for line in b''.join(result).splitlines(True)]

    headers["Content-Type"] = content_type
    # We need str() for Python 2 because of unicode_literals
    headers = sorted((str(k), str(v)) for k, v in headers.items())
    start_response(str(status), headers)
    return result


def main():  # pragma: nocover
    """Simple web server for manual testing"""
    from wsgiref.simple_server import make_server
    srv = make_server('localhost', 8080, application)
    print("Started at http://localhost:8080/")
    srv.serve_forever()


if __name__ == '__main__':
    main()
