#!/usr/bin/env python
"""
Search IRC logs (a CGI script and a WSGI app).

Expects to find logs matching the IRCLOG_GLOB pattern (default: *.log)
in the directory specified by the IRCLOG_LOCATION environment variable.
Expects the filenames to contain a ISO 8601 date (YYYY-MM-DD).

Apache configuration example:

  ScriptAlias /irclogs/search /path/to/irclogsearch.py
  <Location /irclogs/search>
    SetEnv IRCLOG_LOCATION /path/to/irclog/files/
    # Uncomment the following if your log files use a different format
    #SetEnv IRCLOG_GLOB "*.log.????-??-??"
  </Location>

"""

# Copyright (c) 2006-2013, Marius Gedminas
#
# Released under the terms of the GNU GPL
# http://www.gnu.org/copyleft/gpl.html

from __future__ import print_function, unicode_literals

import cgi
import cgitb
import io
import os
import re
import sys
import time
from contextlib import closing

try:
    from urllib import quote
except ImportError:
    from urllib.parse import quote

from .irclog2html import (LogParser, XHTMLTableStyle, NickColourizer,
                          escape, open_log_file, VERSION, RELEASE, CSS_FILE)
from .logs2html import find_log_files


try:
    unicode
except NameError:
    # Python 3.x
    unicode = str


DEFAULT_LOGFILE_PATH = os.path.dirname(__file__)
DEFAULT_LOGFILE_PATTERN = "*.log"

DATE_REGEXP = re.compile('^.*(\d\d\d\d)-(\d\d)-(\d\d)')


HEADER = """\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
          "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html>
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=%(charset)s" />
  <title>%(title)s</title>
  <link rel="stylesheet" href="irclog.css" />
  <meta name="generator" content="irclogsearch.py %(VERSION)s by Marius Gedminas" />
  <meta name="version" content="%(VERSION)s - %(RELEASE)s" />
</head>
<body>""" % {'VERSION': VERSION, 'RELEASE': RELEASE,
             'title': escape("Search IRC logs"), 'charset': 'UTF-8'}

FOOTER = """
<div class="generatedby">
<p>Generated by irclogsearch.py %(VERSION)s by <a href="mailto:marius@pov.lt">Marius Gedminas</a>
 - find it at <a href="http://mg.pov.lt/irclog2html/">mg.pov.lt</a>!</p>
</div>
</body>
</html>""" % {'VERSION': VERSION, 'RELEASE': RELEASE}


class Error(Exception):
    """Application error."""


class SearchStats(object):
    """Search statistics."""

    files = 0
    lines = 0
    matches = 0


class SearchResult(object):
    """Search result -- a single utterance."""

    def __init__(self, filename, link, date, time, event, info):
        self.filename = filename
        self.link = link
        self.date = date
        self.time = time
        self.event = event
        self.info = info


class StdoutWrapper(object):
    # Because I can't wrap sys.stdout with io.TextIOWrapper on Python 2

    def __init__(self, stream):
        self.stream = stream
        self.flush = stream.flush
        self.write = stream.write
        self.closed = False

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False


class SearchResultFormatter(object):
    """Formatter of search results."""

    def __init__(self, stream=None):
        self.stream = stream
        bstream = stream.buffer
        self.style = XHTMLTableStyle(bstream)
        self.nick_colour = NickColourizer()

    def print_prefix(self):
        print(self.style.prefix, file=self.stream)

    def print_html(self, result):
        link = urlescape(result.link)
        if result.event == LogParser.COMMENT:
            nick, text = result.info
            htmlcolour = self.nick_colour[nick]
            self.style.nicktext(result.time, nick, text, htmlcolour, link)
        else:
            if result.event == LogParser.NICKCHANGE:
                text, oldnick, newnick = result.info
                self.nick_colour.change(oldnick, newnick)
            else:
                text = result.info
            self.style.servermsg(result.time, result.event, text, link)

    def print_suffix(self):
        print(self.style.suffix, file=self.stream)


def urlescape(link):
    return escape(quote(link))


def parse_log_file(filename):
    with closing(open_log_file(filename)) as f:
        for row in LogParser(f):
            yield row


def search_irc_logs(query, stats=None, where=None, logfile_pattern=None):
    if not where:
        where = DEFAULT_LOGFILE_PATH
    if not logfile_pattern:
        logfile_pattern = DEFAULT_LOGFILE_PATTERN
    if not stats:
        stats = SearchStats() # will be discarded, but, oh, well
    query = query.lower()
    files = find_log_files(where, logfile_pattern)
    files.reverse() # newest first
    for f in files:
        date = f.date
        link = f.link
        stats.files += 1
        for timestamp, event, info in parse_log_file(f.filename):
            if event == LogParser.COMMENT:
                nick, text = info
                text = nick + ' ' + text
            elif event == LogParser.NICKCHANGE:
                text, oldnick, newnick = info
            else:
                text = unicode(info)
            stats.lines += 1
            if query in text.lower():
                stats.matches += 1
                yield SearchResult(f.filename, link, date, timestamp, event, info)


def print_cgi_headers(stream):
    print("Content-Type: text/html; charset=UTF-8", file=stream)
    print("", file=stream)


def print_search_form(stream=None):
    if stream is None:
        stream = sys.stdout
    print(HEADER, file=stream)
    print("<h1>Search IRC logs</h1>", file=stream)
    print('<form action="" method="get">', file=stream)
    print('<input type="text" name="q" />', file=stream)
    print('<input type="submit" />', file=stream)
    print('</form>', file=stream)
    print(FOOTER, file=stream)


def print_search_results(query, where=None, logfile_pattern=None,
                         stream=None):
    if stream is None:
        stream = sys.stdout
    print(HEADER, file=stream)
    print("<h1>IRC log search results for %s</h1>" % escape(query), file=stream)
    print('<form action="" method="get">', file=stream)
    print('<input type="text" name="q" value="%s" />' % escape(query),
          file=stream)
    print('<input type="submit" />', file=stream)
    print('</form>', file=stream)
    started = time.time()
    date = None
    prev_result = None
    formatter = SearchResultFormatter(stream)
    stats = SearchStats()
    for result in search_irc_logs(query, stats, where=where,
                                  logfile_pattern=logfile_pattern):
        if date != result.date:
            if prev_result:
                formatter.print_suffix()
                prev_result = None
            if date:
                print("  </li>", file=stream)
            else:
                print('<ul class="searchresults">', file=stream)
            print('  <li><a href="%s">%s</a>:' %
                  (urlescape(result.link),
                   result.date.strftime('%Y-%m-%d (%A)')),
                  file=stream)
            date = result.date
        if not prev_result:
            formatter.print_prefix()
        formatter.print_html(result)
        prev_result = result
    if prev_result:
        formatter.print_suffix()
    if date:
        print("  </li>", file=stream)
        print("</ul>", file=stream)
    total_time = time.time() - started
    print("<p>%d matches in %d log files with %d lines (%.1f seconds).</p>"
          % (stats.matches, stats.files, stats.lines, total_time),
          file=stream)
    print(FOOTER, file=stream)

    return formatter # destroying it closes the stream, breaking the result


def rewrap_stdout():
    if hasattr(sys.stdout, 'buffer'):
        stream = sys.stdout.buffer # Python 3
    else:
        stream = StdoutWrapper(sys.stdout) # Python 2
    return io.TextIOWrapper(stream, 'ascii',
                            errors='xmlcharrefreplace',
                            line_buffering=True)


def search_page(stream, form, where, logfile_pattern):
    if "q" not in form:
        print_search_form(stream)
    else:
        search_text = form["q"].value
        if isinstance(search_text, bytes):
            search_text = search_text.decode('UTF-8')
        return print_search_results(search_text, stream=stream, where=where,
                                    logfile_pattern=logfile_pattern)


def get_path(environ):
    path = environ.get('PATH_INFO', '/')
    path = path[1:]  # Remove the leading slash
    if '/' in path or '\\' in path:
        return None
    return path if path != '' else 'index.html'


def wsgi(environ, start_response):
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
    elif path == 'search':
        fmt = search_page(stream, form, logfile_path, logfile_pattern)
        result = [stream.buffer.getvalue()]
    elif path == 'irclog.css':
        content_type = "text/css"
        try:
            with open(CSS_FILE, "rb") as f:
                result = [f.read()]
        except IOError:
            status = "404 Not Found"
            result = [b"Not found"]
    else:
        if path.endswith('.css'):
            content_type = "text/css"
        if path.endswith('.log') or path.endswith('.txt'):
            content_type = "text/plain"
        try:
            with open(os.path.join(logfile_path, path), "rb") as f:
                result = [f.read()]
        except IOError:
            if path == 'index.html':
                # no index? redirect to search page
                status = "302 Found"
                result = [b"Try /search"]
                headers['Location'] = '/search'
            else:
                status = "404 Not Found"
                result = [b"Not found"]

    headers["Content-Type"] = content_type
    # We need str() for Python 2 because of unicode_literals
    headers = sorted((str(k), str(v)) for k, v in headers.items())
    start_response(str(status), headers)
    return result


def serve():  # pragma: nocover
    """Simple web server for manual testing"""
    from wsgiref.simple_server import make_server
    srv = make_server('localhost', 8080, wsgi)
    print("Started at http://localhost:8080/")
    srv.serve_forever()


def main():
    """CGI script"""
    cgitb.enable()
    logfile_path = os.getenv('IRCLOG_LOCATION') or DEFAULT_LOGFILE_PATH
    logfile_pattern = os.getenv('IRCLOG_GLOB') or DEFAULT_LOGFILE_PATTERN
    form = cgi.FieldStorage()
    stream = rewrap_stdout()
    print_cgi_headers(stream)
    search_page(stream, form, logfile_path, logfile_pattern)


if __name__ == '__main__':
    main()
