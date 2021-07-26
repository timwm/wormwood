#!/bin/python3
"""
simple script to serve 7zip archived files on-the-fly, with even directory indexing :-)
"""

import os, subprocess
from datetime import datetime
from urllib import parse as urlparse

# presume url begins with /
ARCHIVE_DIR = "/archives/"


def print_headers(mime="text/plain", **headers):
    mime_info = mime.partition( ';' )
    dispositions = [ 'application/octet-stream', 'application/x-011-' ]
    ret = "Content-Type: {0}; charset=utf-8\r\n".format( mime_info[0] )\
        + "X-Powered-By: 011/r"+ datetime.utcfromtimestamp( 1622376173.688331 )\
            .strftime( "%FT%T" ) + "\r\n"
    for i in dispositions:
        if mime_info[0].startswith( i ):
            ret += "Content-Disposition: attachment; filename={0}\r\n"\
                    .format( mime_info[2] )
    for h in headers:
        ret += "{0}: {1}\r\n".format( h, headers[h] )
    # capture written bytes
    _ = os.write( os.sys.stdout.fileno(), bytes( ret + "\r\n", encoding="utf8" ) )


def redirect( rloc ):
    log( 301, 0, suffix=" -> {0}\n".format( rloc ) )
    os.sys.exit( print_headers( **{
        "Status": "301 Moved Permanently",
        "Location":  os.environ["REQUEST_SCHEME"] +"://"\
                + os.environ["HTTP_HOST"] + rloc
    }) )


def get_contents( resource, code=None ):
    from re import compile as re_compile
    prog_map = {
        '.*\.php[567]?$': ['php', '-q', '-d', 'html_errors=1', '-d', 'docref_root='+ os.environ['HTTP_HOST'] + ARCHIVE_DIR +'lingua/php_manual_en/php-chunked-xhtml', '-f', '%s'],
        '.*\.py[23]?$': ['python', '-B', '%s']
    }
    handler = ret = None
    filename = resource

    if code is not None:
        from tempfile import mkstemp
        fd, filename = mkstemp()
        os.write( fd, code )
        os.close( fd )

    for p, c in prog_map.items():
        if re_compile( p ).match( resource ):
            for i, a in enumerate(c):
                if a == '%s': c[i] = filename
            handler = p
            os.chdir( os.path.dirname( resource ))
            ret = subprocess.run( c, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL ).stdout
    if ret is None:
        with open( filename, 'rb' ) as fh: ret = fh.read()

    if code is not None: os.remove( filename )

    return (200, ret, {}, get_mime( resource ) if handler is None else 'text/html' )


def get_mime( filename ):
    top, _, ext = os.path.basename( filename ).rpartition( '.' )
    if not top:
        return "application/octet-stream;" + ext
    mime_file = "/data/data/com.termux/files/usr/etc/apache2/mime.types"
    conf = get_conf( mime_file, ext, [1,999,0,1] )
    return ( conf and conf[0] or "application/x-011-" + ext.lower() )\
            + ";{0}.{1}".format( top, ext )


def get_conf( filename, needle, indices=[0,0,0,0] ):
    """
    indices = [<haystack start>, <haystack end>, <return start>, <return end>]
    """
    with open( filename, 'r' ) as fh:
        for line in fh:
            haystack = line.strip( '\n' ).split()
            if not haystack or haystack[0][0] == '#': continue
            for h in haystack[ indices[0]:indices[1] ]:
                if needle == h:
                    return haystack[ indices[2] : indices[3] ]
    return []


def extract( archive, entry, url, attempt=True ):
    args = [ "-mmt8", "-so", "-bd", "-spd", "-bsp2", "-bse2", "-bb0", archive, entry ]
    if attempt:
        # We are not using stderr at the moment
        entries = subprocess.run( [ "7z", "l" ] + args, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL ).stdout.split( b'\n' )[13:-3] 
        length = len( entries )
        if length > 2 or length == 2 and entries[1].split()[2].lower()\
                .find( b'd' ) > -1: 
            return dirlist( archive, url, [ entries, entry ] )
        elif length < 2:
            if length:
                return error_doc( 404, url, "Can NOT extract. File NOT FOUND" )
            # it's not an archive
            return get_contents( archive + '/' + entry if entry else archive )
    # We are not using stderr at the moment
    return get_contents( entry, subprocess.run( [ "7z", "e" ] + args, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL ).stdout )


def serve_files():
    # just put here to help with some other tests was doing with HAproxy and
    # varnishcache, it's absolutely stupid code; non realistic. You MAY delete it.
    if os.environ['REQUEST_METHOD'] == "HEAD":
        return print_headers( **{ "Status": "302 Found", "Content-Length": '0' } )

    url = urlparse.unquote( os.environ["REQUEST_URI"] )
    # path = [<server root>, <archive name>, </>, <file path>]
    path = [ os.path.normpath( os.environ["DOCUMENT_ROOT"] ), ]
    path += os.path.normpath( urlparse.urlparse( url ).path )\
            .removeprefix( ARCHIVE_DIR ).partition( '/' )
    resource = path[0] + ( ARCHIVE_DIR if path[1] else '' ) + ''.join( path[1:] )
    ret = tuple() # [ <response>, {<headers>}, <mime type> ]

    if os.path.isdir( resource ): ret = dirlist( resource, url )
    elif path[1]:
        # URI prefix is ARCHIVE_DIR
        archive = path[0] + ARCHIVE_DIR + path[1]
        while os.path.isdir( archive ):
            top, _, path[3] = path[3].partition( '/' )
            archive += '/' + top
        if os.path.exists( archive ):
            ret = extract( archive, path[3], url )
        else:
            ret = error_doc( 404, url, "NO such file or archive" )
    elif os.path.exists( resource ):
        # if not path[3]: redirect request of / to ARCHIVE_DIR
        ret = get_contents( resource )
    else:
        ret = error_doc( 404, url, "File NOT FOUND" )

    ret_len = len( ret[1] )
    ret[2].update( { "Content-Length": str( ret_len ) } )

    log( ret[0], ret_len )
    print_headers( ret[3], **ret[2] )
    # capture written bytes
    _ = os.write( os.sys.stdout.fileno(), ret[1] )


def dirlist( path, url, archive_entries=None ):
    if url[-1] != '/':
        return redirect( url + '/' )
    index_files = [] #[ "index.html", "default.html", "readme", "readme.md" ]
    wp = os.path.normpath( url )
    ret = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN"><html><head>'\
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>'\
        + "<title>Index of " + wp + "</title></head><body><h1>Index of " + wp \
        + "</h1><hr><ul>"
    if wp != '/':
        ret += '<li><a href="' + urlparse.quote( wp.rpartition( '/' )[0] )\
            + '/"> ..</a>'
    if archive_entries is None:
        for entry in os.listdir( path ):
            # handle broken symlinks
            if not os.path.exists( path + '/' + entry ): continue
            ret += '<li><a href="' + urlparse.quote( entry )
            if os.path.isdir( path + '/' + entry ): ret += '/'
            else:
                for i in index_files:
                    if entry.lower() == i:
                        return get_contents( path + '/' + entry )
            ret += '"> ' + entry + '</a>'
    else:
        # +2 or +1: cater for b' ' and b'/'
        index = archive_entries[0][0].rfind( b' ' ) + ( archive_entries[1] and \
                len( archive_entries[1] ) + 2 or 1 )
        reg = dict()
        for archive_entry in archive_entries[0][1:]:
            meta = archive_entry[ index: ].partition( b'/' )
            if reg.get( meta[0] ) or not meta[0]: continue
            entry = str( meta[0] )[2:-1]

            ret += '</a><li><a href="'+ urlparse.quote( entry )
            if archive_entry.split()[2].lower().find( b'd' ) > -1: ret += '/'
            else:
                for i in index_files:
                    if entry.lower() == i:
                        return extract( path, archive_entries[1] + entry,\
                                url, attempt=False )
            ret += '"> ' + entry + '</a>'
            reg[ meta[0] ] = True

    return ( 200, bytes( ret + "</ul></body></html>", encoding="utf8" ), {
        "Pragma": "no-cache", "Expires": '0',
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"
        }, "text/html"
    )


def error_doc( code, url, info='' ):
    db = { 404: "Not Found", 500: "Internal Server Error" }
    ret = "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 3.2 Final//EN\"><html><head>"\
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>'\
        "<title>" + str( code ) + ' ' + db[ code ] + "</title></head><body>"\
        "<center><p><br><h1>"+ str( code ) + ' ' + db[ code ] + "</h1><hr>"\
        "Could NOT process requested resource <b>" + url + "</b><br>"\
        + info + "<br>that's all I know ...sorry :(</p><br><br><p>Maybe you'd like"\
        + ' going to the <a href="/">homepage</a>.</p></center></body></html>'

    return ( code, bytes( ret, encoding="utf8" ), {
        "Status": str( code ) + ' ' + db[ code ], "Pragma": "no-cache",
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Expires": "0"
        }, "text/html"
    )


def log( code, length, prefix='', suffix='\n' ):
    log_file = "/data/data/com.termux/files/home/.011/chroot/var/log/.011/"\
            "serve_archive_files.log"
    with open( log_file, "ab" ) as fh:
        msg = '[' + datetime.utcnow().strftime( '%FT%T.%f' ) + ']' + prefix
        for k in [ "HTTP_HOST", "REQUEST_METHOD", "REQUEST_URI" ]:
            msg += ' ' + os.environ.get( k, '-' )
        msg += ' ' + str( code ) + ' ' + str( length ) + suffix
        fh.write( bytes( msg, encoding='utf8' ) )


if __name__ == "__main__":
    serve_files()
