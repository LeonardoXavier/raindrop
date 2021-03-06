# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Raindrop.
#
# The Initial Developer of the Original Code is
# Mozilla Messaging, Inc..
# Portions created by the Initial Developer are Copyright (C) 2009
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#

from email.utils import parseaddr
from email._parseaddr import AddressList
from email.message import Message

def decode_body_part(docid, body_bytes, charset=None):
    # Convert a 'text/*' encoded byte string to *some* unicode object,
    # ignoring (but logging) unicode errors we may see in the wild...
    # TODO: This sucks; we need to mimick what firefox does in such cases...
    try:
        body = body_bytes.decode(charset or 'ascii')
    except (UnicodeError, LookupError), exc:
        # UnicodeError == known encoding, bad data.
        # LookupError == unknown encoding
        # No need to make lots of log noise for something beyond our
        # control...
        logger.debug("Failed to decode body in document %r from %r: %s",
                     docid, charset, exc)
        # no charset failed to decode as declared - just go straight to
        # latin-1! (is 'ignore' needed here?)
        body = body_bytes.decode('latin-1', 'ignore')
    return body


def extract_preview(body):
    lines = body.split('\n')
    # get rid of blank lines
    lines = [line.strip() for line in lines if line.strip()]
    preview_lines = []

    for (i, line) in enumerate(lines):
        if not line.startswith('>') and line.endswith(':') and \
            i+1 < len(lines)-1 and lines[i+1].startswith('>'):
            continue
        preview_lines.append(line)
    trimmed_preview_lines = []
    for (i, line) in enumerate(preview_lines):
        if line.startswith('>'):
            if trimmed_preview_lines and trimmed_preview_lines[-1] != '[...]':
                trimmed_preview_lines.append('[...]')
        else:
            trimmed_preview_lines.append(line)
    if trimmed_preview_lines and trimmed_preview_lines[0] == '[...]':
        trimmed_preview_lines = trimmed_preview_lines[1:]
    preview_body = '\n'.join(trimmed_preview_lines)
    return preview_body[:140] + (preview_body[140:] and '...') # cute trick

def fill_identity_info(val, identity_list, display_list):
    a = AddressList(val)
    for name, addr in a.addresslist:
        identity_list.append(['email', addr.lower()])
        display_list.append(name)

def handler(doc):
    # a 'rfc822' stores 'headers' as a dict, with each entry being a list.
    # We only care about headers which rfc5322 must appear 0 or 1 times, so
    # flatten the header values here...
    headers = dict((k, v[0]) for (k, v) in doc['headers'].iteritems())
    # for now, 'from' etc are all tuples of [identity_type, identity_id]
    callbacks = []
    ret = {}
    if 'from' in headers:
        name, addr = parseaddr(headers['from'])
        ret['from'] = ['email', addr.lower()]
        ret['from_display'] = name

    if 'to' in headers:
        id_list = ret['to'] = []
        disp_list = ret['to_display'] = []
        fill_identity_info(headers['to'], id_list, disp_list)

    if 'cc' in headers:
        id_list = ret['cc'] = []
        disp_list = ret['cc_display'] = []
        fill_identity_info(headers['cc'], id_list, disp_list)

    if 'subject' in headers:
        ret['subject'] = headers['subject']
    if 'timestamp' in doc:
        ret['timestamp'] = doc['timestamp']

    # body handling
    if doc.get('multipart'):
        infos = doc['multipart_info']
    else:
        aname, attach = get_schema_attachment_info(doc, 'body')
        infos = [{'content_type': attach['content_type'],
                  'name': 'body'}]

    parts = []
    docid = doc['_id']
    for info in infos:
        # Use the email package to help parse the charset...
        m = Message()
        m['content-type'] = info['content_type']
        charset = m.get_content_charset()
        ct = m.get_content_type()
        if ct == 'text/plain':
            name = info['name']
            content = open_schema_attachment(doc, name)
            parts.append(decode_body_part(docid, content, charset))

        # else: we should annotate the object with non-plaintext
        # attachment information XXX
    ret['body'] = '\n'.join(parts)

    ret['body_preview'] = extract_preview(ret['body'])
    try:
        # If the provider could supply tags then pass them on
        ret['tags'] = doc['tags']
    except KeyError:
        pass
    emit_schema('rd.msg.body', ret)
