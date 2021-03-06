"""
Handles HTTP caching.
"""

import atexit
from hashlib import md5
import os
from os import stat
from tempfile import mkstemp
from time import time

from aspen import Response
from aspen.testing.client import Client

from liberapay.utils import b64encode_s, find_files


ETAGS = {}


def compile_assets(website):
    client = Client(website.www_root, website.project_root)
    client._website = website
    for spt in find_files(website.www_root+'/assets/', '*.spt'):
        filepath = spt[:-4]                         # /path/to/www/assets/foo.css
        urlpath = spt[spt.rfind('/assets/'):-4]     # /assets/foo.css
        try:
            # Remove any existing compiled asset, so we can access the dynamic
            # one instead (Aspen prefers foo.css over foo.css.spt).
            os.unlink(filepath)
        except:
            pass
        content = client.GET(urlpath).body
        tmpfd, tmpfpath = mkstemp(dir='.')
        os.write(tmpfd, content)
        os.close(tmpfd)
        os.rename(tmpfpath, filepath)
    compilation_time = time()
    atexit.register(lambda: clean_assets(website.www_root, compilation_time))


def clean_assets(www_root, older_than=None):
    for spt in find_files(www_root+'/assets/', '*.spt'):
        try:
            path = spt[:-4]
            if older_than and os.stat(path).st_mtime > older_than:
                continue
            os.unlink(path)
        except:
            pass


def asset_etag(path):
    if path.endswith('.spt'):
        return ''
    mtime = stat(path).st_mtime
    if path in ETAGS:
        h, cached_mtime = ETAGS[path]
        if cached_mtime == mtime:
            return h
    with open(path, 'rb') as f:
        h = b64encode_s(md5(f.read()).digest())
    ETAGS[path] = (h, mtime)
    return h


# algorithm functions

def get_etag_for_file(dispatch_result):
    return {'etag': asset_etag(dispatch_result.match)}


def try_to_serve_304(dispatch_result, request, etag):
    """Try to serve a 304 for static resources.
    """
    if not etag:
        # This is a request for a dynamic resource.
        return

    qs_etag = request.line.uri.querystring.get('etag')
    if qs_etag and qs_etag != etag:
        # Don't serve one version of a file as if it were another.
        raise Response(410)

    headers_etag = request.headers.get('If-None-Match')
    if not headers_etag:
        # This client doesn't want a 304.
        return

    if headers_etag != etag:
        # Cache miss, the client sent an old or invalid etag.
        return

    # Huzzah!
    # =======
    # We can serve a 304! :D

    raise Response(304)


def add_caching_to_response(response, request=None, etag=None):
    """Set caching headers.
    """
    if not etag:
        # This is a dynamic resource, disable caching by default
        if 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = 'no-cache'
        return

    assert request is not None  # sanity check

    if response.code not in (200, 304):
        return

    # https://developers.google.com/speed/docs/best-practices/caching
    response.headers['Etag'] = etag

    if request.line.uri.querystring.get('etag'):
        # We can cache "indefinitely" when the querystring contains the etag.
        response.headers['Cache-Control'] = 'public, max-age=31536000'
    else:
        # Otherwise we cache for 5 seconds
        response.headers['Cache-Control'] = 'public, max-age=5'
