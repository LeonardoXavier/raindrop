# This extension extracts information about a mailing list through which
# a message has been sent.  It creates rd.mailing-list docs for the mailing
# lists, one per list, and rd.msg.email.mailing-list docs for the emails,
# one per email sent through a list.  All the information about a list
# is stored in its rd.mailing-list doc; a rd.msg.email.mailing-list doc
# just links an email to its corresponding list.

# We extract mailing list info from RFC 2369 headers, which look like this:
#
#   Mailing-List: list raindrop-core@googlegroups.com;
#       contact raindrop-core+owner@googlegroups.com
#   List-Id: <raindrop-core.googlegroups.com>
#   List-Post: <mailto:raindrop-core@googlegroups.com>
#   List-Help: <mailto:raindrop-core+help@googlegroups.com>
#   List-Unsubscribe: <http://googlegroups.com/group/raindrop-core/subscribe>,
#       <mailto:raindrop-core+unsubscribe@googlegroups.com>

# Here's another example (with some other headers that may be relevant):

#   Archived-At: <http://www.w3.org/mid/49F0D9FC.6060103@w3.org>
#   Resent-From: public-webapps@w3.org
#   X-Mailing-List: <public-webapps@w3.org> archive/latest/3067
#   Sender: public-webapps-request@w3.org
#   Resent-Sender: public-webapps-request@w3.org
#   Precedence: list
#   List-Id: <public-webapps.w3.org>
#   List-Help: <http://www.w3.org/Mail/>
#   List-Unsubscribe: <mailto:public-webapps-request@w3.org?subject=unsubscribe>

# This extension also handles most of the process of Raindrop-assisted list
# unsubscription.  Once a user has requested unsubscription via the Raindrop
# front-end, this extension fields the request from the mailing list to confirm
# the unsubscription.  Afterwards it fields the notification from the list
# that the user has been unsubscribed.

# There is no standard for these messages; we have to employ unique techniques
# for each mailing list server software.  For now we do this by hardcoding
# detectors for major servers; in the future there might be a way to abstract
# the detectors into a set of declarations (such that detectors can be simpler
# extensions of this extension) or to define a standard mechanism that we get
# mailing list software vendors to adopt.

# Life cycle of Raindrop-assisted unsubscription:
#
# Initial State:
#   The mailing list status is "subscribed".
#
# Step 1: User Requests Unsubscription
#   The user tells Raindrop's front-end to unsubscribe from a mailing list.
#   Raindrop's front-end sends an unsubscription request to the mailing list.
#   Raindrop's front-end sets the mailing list status to "unsubscribe-pending".
#
# Step 2: List Requests Confirmation
#   The mailing list requests confirmation of the unsubscription request.
#   This extension responds with confirmation of the unsubscription request.
#   This extension sets the mailing list status to "unsubscribe-confirmed".
#
# Final State: User is Unsubscribed
#   The mailing list sends an unsubscription notification to the user.
#   This extension sets the mailing list status to "unsubscribed".

# TODO: split this extension into two extensions: one that creates/updates
# mailing list documents and handles unsubscription messages; and another that
# simply associates messages with their lists.  That will improve performance,
# because the latter task performs no queries so can be batched.

import re
import time
from email.utils import mktime_tz, parsedate_tz

def _get_subscribed_identity(headers):
    # Get the user's email identities and determine which one is subscribed
    # to the mailing list that sent a message with the given headers.

    identities = get_my_identities()
    logger.debug("getting subscribed identity from options: %s", identities);

    email_identities = [i for i in identities if i[0] == 'email'];

    # TODO: figure out what to do if the user has no email identities.
    if len(email_identities) == 0:
        logger.debug("no email identities")
        return None

    # If the user only has one email identity, it *should* be the one subscribed
    # to the list.
    # XXX could an alias not in the set of identities be subscribed to the list?
    if len(email_identities) == 1:
        logger.debug("one email identity: %s", email_identities[0])
        return email_identities[0]

    logger.debug("multiple email identities: %s", email_identities);

    # Index identities by email address to make it easier to find the right one
    # based on information in the message headers.
    email_identities_by_address = {}
    for i in email_identities:
        email_identities_by_address[i[1]] = i

    # If the user has multiple email identities, try to narrow down the one
    # subscribed to the list using the Delivered-To header, which lists will
    # sometimes set to the subscribed email address.
    # TODO: figure out what to do if there are multiple Delivered-To headers.
    if 'delivered_to' in headers:
        logger.debug("Delivered-To headers: %s", headers['delivered-to']);
        if headers['delivered-to'][0] in email_identities_by_address:
            identity = email_identities_by_address[headers['delivered-to'][0]]
            logger.debug("identity from Delivered-To header: %s", identity)
            return identity

    # Try to use the Received headers to narrow down the identity.
    #
    # We only care about Received headers that contain "for <email address>"
    # in them.  Of those, it seems like the one(s) at the end of the headers
    # contain the address of the list itself (f.e. example@googlegroups.com),
    # while those at the beginning of the headers contain the address to which
    # the message was ultimately delivered (f.e. jonathan.smith@example.com),
    # which might not be the same as the one by which the user is subscribed,
    # if the user is subscribed via an alias (f.e. john@example.com).
    #
    # But the alias, if any, tends to be found somewhere in the middle of
    # the headers, between the list address and the ultimate delivery address,
    # so to maximize our chances of getting the right identity, we start from
    # the end of the headers and work our way forward until we find an address
    # in the user's identities.
    if 'received' in headers:
        logger.debug("Received headers: %s", headers['received']);
        # Copy the list so we don't mess up the original when we reverse it.
        received = headers['received'][:]
        received.reverse()
        for r in received:
            # Regex adapted from http://www.regular-expressions.info/email.html.
            match = re.search(r"for <([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,4})>",
                              r, re.I)
            if match:
                logger.debug("address from Received header: %s", match.group(1))
                if match.group(1) in email_identities_by_address:
                    identity = email_identities_by_address[match.group(1)]
                    logger.debug("identity from Received header: %s", identity)
                    return identity

    # We have multiple identities, and we haven't narrowed down the one that
    # is subscribed to the list.  So we don't return anything, and we'll make
    # the front-end figure out what to do in this situation. For example,
    # it could prompt the user for the address with which they are subscribed
    # to the list.  Alternately, it could send unsubscribe requests from all
    # the user's identities.
    logger.debug("couldn't determine subscribed identity")
    return None

def _update_list(list, name, message):
    # Update the list based on the information contained in the headers
    # of the provided message.

    # For now we just reflect the literal values of the various headers
    # into the doc; eventually we'll want to do some processing of them
    # to make life easier on the front-end.

    # Note that we don't remove properties not provided by the message,
    # since it doesn't necessarily mean those properties are no longer
    # valid.  This might be an admin message that doesn't include them
    # (Mailman sends these sometimes).

    # Whether or not we changed the list.  We return this so callers
    # who are updating a list that is already stored in the datastore
    # know whether or not they need to update the datastore.
    changed = False

    # Update the name (derived from the list-id header).
    if name != "" and ('name' not in list or list['name'] != name):
        list['name'] = name
        changed = True

    # Update the properties derived from list- headers.
    # XXX reflect other list-related headers like (X-)Mailing-List,
    # Archived-At, and X-Mailman-Version?
    for key in ['list-post', 'list-archive', 'list-help', 'list-subscribe',
                'list-unsubscribe']:
        if key in message['headers']:
            val = message['headers'][key][0]
            # We strip the 'list-' prefix when writing the key to the list.
            if key[5:] not in list or list[key[5:]] != val:
                logger.debug("setting %s to %s", key[5:], val)
                list[key[5:]] = val
                changed = True

    return changed

def _create_or_update_list(message, list_id, list_name, timestamp):
    msg_id = message['headers']['message-id'][0]

    keys = [['rd.core.content', 'key-schema_id',
             [['mailing-list', list_id], 'rd.mailing-list']]]
    result = open_view(keys=keys, reduce=False, include_docs=True)
    # Build a map of the keys we actually got back.
    rows = [r for r in result['rows'] if 'error' not in r]

    if rows:
        logger.debug("FOUND LIST %s for message %s", list_id, msg_id)
        assert 'doc' in rows[0], rows

        list = rows[0]['doc']

        # If this message is newer than the last one from which we derived
        # mailing list information, update the mailing list record with any
        # updated information in this message.
        if 'changed_timestamp' not in list \
                or timestamp >= list['changed_timestamp']:
            logger.debug("UPDATING LIST %s from message %s", list_id, msg_id)
            changed = _update_list(list, list_name, message)
            if changed:
                logger.debug("LIST CHANGED; saving updated list")
                list['changed_timestamp'] = timestamp
                update_documents([list])

    else:
        logger.debug("CREATING LIST %s for message %s", list_id, msg_id)

        list = {
            'id': list_id,
            'status': 'subscribed',
            'changed_timestamp': timestamp
        }

        identity = _get_subscribed_identity(message['headers'])
        if identity:
            list['identity'] = identity

        _update_list(list, list_name, message)

        emit_schema('rd.mailing-list', list, rd_key=["mailing-list", list_id])

def _handle_unsubscribe_confirm_request_google_groups(message):
    # The list ID is the part of the Reply-To header before the plus sign
    # followed by ".googlegroups.com".  For example, based on the following
    # header the ID is mozilla-labs-personas.googlegroups.com:
    #     Reply-To: mozilla-labs-personas+unsubconfirm-ttVMSQwAAAAyzbmfKdXzOjrwK-0FmDri@googlegroups.com
    list_id = message['headers']['reply-to'][0].split('+')[0] + '.googlegroups.com'
    logger.info('received confirm unsubscribe request from %s', list_id)

    keys = [['rd.core.content', 'key-schema_id',
     [['mailing-list', list_id], 'rd.mailing-list']]]
    result = open_view(keys=keys, reduce=False, include_docs=True)
    # Build a map of the keys we actually got back.
    rows = [r for r in result['rows'] if 'error' not in r]

    if rows:
        list = rows[0]['doc']
        logger.info('found list in datastore')
        if (list['status'] == 'unsubscribe-pending'):
            logger.info('list status is unsubscribe-pending; confirming')
            list['status'] = 'unsubscribe-confirmed'
            update_documents([list])

            # Confirmation entails responding to the address in the Reply-To
            # header, which contains the confirmation token, f.e.:
            #   mozilla-labs-personas+unsubconfirm-ttVMSQwAAAAyzbmfKdXzOjrwK-0FmDri@googlegroups.com
            confirmation = {
              'from': list['identity'],
              # TODO: use the user's name in the from_display.
              'from_display': list['identity'][1],
              'to': [['email', message['headers']['reply-to'][0]]],
              'to_display': [''],
              'subject': '',
              'body': '',
              'outgoing_state': 'outgoing'
            };

            # TODO: make a better rd_key.
            emit_schema('rd.msg.outgoing.simple', confirmation,
                        rd_key=['manually_created_doc', time.time()])
        else:
            logger.info('list status is not unsubscribe-pending; ignoring')
    else:
        logger.info("didn't find list; can't confirm request")

def _handle_unsubscribe_confirmation_google_groups(message, list_id, timestamp):
    # Although the caller tries to extract the list ID from the list-ID header,
    # Google Groups unsubscribe confirmations don't contain that header,
    # so the list_id parameter has no value here.  Instead, we have to extract
    # it ourselves from the Subject header.
    #
    # The list ID is the part of the Subject header after the text "Google
    # Groups: You have unsubscribed from " followed by ".googlegroups.com".
    # For example, based on the following header, the list ID would be
    # mozilla-labs-personas.googlegroups.com:
    #   Subject: Google Groups: You have unsubscribed from mozilla-labs-personas
    # TODO: figure out how to extract the list ID from a localized subject.
    list_id = message['headers']['subject'][0]. \
              split('Google Groups: You have unsubscribed from ', 1)[1] + \
              '.googlegroups.com'
    logger.info('received unsubscription confirmation from %s', list_id)

    keys = [['rd.core.content', 'key-schema_id',
     [['mailing-list', list_id], 'rd.mailing-list']]]
    result = open_view(keys=keys, reduce=False, include_docs=True)
    # Build a map of the keys we actually got back.
    rows = [r for r in result['rows'] if 'error' not in r]

    if not rows:
        logger.info("didn't find list; can't update it")
        return

    logger.info('found list in datastore')

    list = rows[0]['doc']

    if (list['status'] == 'unsubscribed'):
        logger.info('list status is already unsubscribed; ignoring')
        return

    # If the user is using Raindrop to unsubscribe from the list,
    # then the list status should be "unsubscribe-confirmed" at this point.
    # However, when a user starts using Raindrop and imports a bunch
    # of messages, the list status might be "subscribed" here, depending on
    # the order in which the messages are imported.
    #
    # Nevertheless, we should still set the status to "unsubscribed" now
    # to reflect that the user is no longer subscribed to the list.  If we
    # subsequently process a message that indicates the user later
    # resubscribed to the list, we'll set the status back to "subscribed"
    # at that point.

    # If the list has been changed by a newer message, that means the user
    # has received a message from the list since this unsubscription
    # confirmation, which means that either the unsubscription didn't work
    # or (more likely) the user resubscribed to the list.  In either case,
    # we shouldn't set the list to unsubscribed here, since it isn't.
    if 'changed_timestamp' in list \
            and timestamp < list['changed_timestamp']:
        logger.info('list has been changed by a newer message; ignoring')
        return

    logger.info('list status is %s; setting it to unsubscribed',
                list['status'])

    list['status'] = 'unsubscribed'
    update_documents([list])

def _handle_unsubscribe_confirm_request_mailman(message, list_id):
    if not list_id:
        logger.info("couldn't determine list ID; ignoring")
        return
    logger.info('received confirm unsubscribe request from %s', list_id)

    keys = [['rd.core.content', 'key-schema_id',
     [['mailing-list', list_id], 'rd.mailing-list']]]
    result = open_view(keys=keys, reduce=False, include_docs=True)
    # Build a map of the keys we actually got back.
    rows = [r for r in result['rows'] if 'error' not in r]

    if not rows:
        logger.info("didn't find list; can't confirm request")
        return

    logger.info('found list in datastore')

    list = rows[0]['doc']

    if (list['status'] != 'unsubscribe-pending'):
        logger.info('list status is not unsubscribe-pending; ignoring')
        return

    logger.info('list status is unsubscribe-pending; confirming')

    # Confirmation entails responding to the address in the Reply-To
    # header, which contains the confirmation token, f.e.:
    #   test-confirm+018e404890076d94e6026d8333c887f8edd0c41f@lists.mozilla.org
    # Also, the subject line must contain the subject of the message
    # requesting confirmation, f.e.:
    #   "Your confirmation is required to leave the test mailing list"
    confirmation = {
      'from': list['identity'],
      # TODO: use the user's name in the from_display.
      'from_display': list['identity'][1],
      'to': [['email', message['headers']['reply-to'][0]]],
      'to_display': [''],
      'subject': message['headers']['subject'][0],
      'body': '',
      'outgoing_state': 'outgoing'
    };

    # TODO: make a better rd_key.
    emit_schema('rd.msg.outgoing.simple', confirmation,
                rd_key=['manually_created_doc', time.time()])

    list['status'] = 'unsubscribe-confirmed'
    update_documents([list])

def _handle_unsubscribe_confirmation_mailman(message, list_id, timestamp):
    if not list_id:
        logger.info("couldn't determine list ID; ignoring")
        return
    logger.info('received unsubscription confirmation from %s', list_id)

    keys = [['rd.core.content', 'key-schema_id',
     [['mailing-list', list_id], 'rd.mailing-list']]]
    result = open_view(keys=keys, reduce=False, include_docs=True)
    # Build a map of the keys we actually got back.
    rows = [r for r in result['rows'] if 'error' not in r]

    if not rows:
        logger.info("didn't find list; can't update it")
        return

    logger.info('found list in datastore')

    list = rows[0]['doc']

    if (list['status'] == 'unsubscribed'):
        logger.info('list status is already unsubscribed; ignoring')
        return

    # If the user is using Raindrop to unsubscribe from the list,
    # then the list status should be "unsubscribe-confirmed" at this point.
    # However, when a user starts using Raindrop and imports a bunch
    # of messages, the list status might be "subscribed" here, depending on
    # the order in which the messages are imported.
    #
    # Nevertheless, we should still set the status to "unsubscribed" now
    # to reflect that the user is no longer subscribed to the list.  If we
    # subsequently process a message that indicates the user later
    # resubscribed to the list, we'll set the status back to "subscribed"
    # at that point.

    # If the list has been changed by a newer message, that means the user
    # has received a message from the list since this unsubscription
    # confirmation, which means that either the unsubscription didn't work
    # or (more likely) the user resubscribed to the list.  In either case,
    # we shouldn't set the list to unsubscribed here, since it isn't.
    if 'changed_timestamp' in list \
            and timestamp < list['changed_timestamp']:
        logger.info('list has been changed by a newer message; ignoring')
        return

    logger.info('list status is %s; setting it to unsubscribed',
                list['status'])

    list['status'] = 'unsubscribed'
    update_documents([list])

def handler(message):
    # Extract the timestamp of the message we're processing.
    timestamp = 0
    if 'date' in message['headers']:
        date = message['headers']['date'][0]
        if date:
            try:
                timestamp = mktime_tz(parsedate_tz(date))
            except (ValueError, TypeError), exc:
                logger.debug('Failed to parse date %r in message %r: %s',
                             date, message['_id'], exc)

    if 'list-id' in message['headers']:
        logger.debug("list-* headers: %s", [h for h in message['headers'].keys()
                                            if h.startswith('list-')])

        # Extract the ID and name of the mailing list from the list-id header.
        # Some mailing lists give only the ID, but others (Google Groups, Mailman)
        # provide both using the format 'NAME <ID>', so we extract them separately
        # if we detect that format.
        list_id = message['headers']['list-id'][0]
        match = re.search('([\W\w]*)\s*<(.+)>.*', list_id)
        if (match):
            logger.debug("complex list-id header with ID '%s' and name '%s'",
                         match.group(2), match.group(1))
            list_id = match.group(2)
            list_name = match.group(1)
        else:
            logger.debug("simple list-id header with ID '%s'", list_id)
            list_name = ""

        _create_or_update_list(message, list_id, list_name, timestamp)
        logger.debug("linking message %s to its mailing list %s",
                     message['headers']['message-id'][0], list_id)
        emit_schema('rd.msg.email.mailing-list', { 'list_id': list_id })
    else:
        list_id = None

    # Google Groups Step 2 (List Requests Confirmation) Detector
    # A request is a message from the address "noreply@googlegroups.com"
    # with an "X-Google-Loop: unsub_requested" header.
    if 'from' in message['headers'] and \
            message['headers']['from'][0] == "noreply@googlegroups.com" and \
            'x-google-loop' in message['headers'] and \
            message['headers']['x-google-loop'][0] == 'unsub_requested' and \
            'reply-to' in message['headers']:
        _handle_unsubscribe_confirm_request_google_groups(message)

    # Google Groups Step 3 (User is Unsubscribed) Detector
    # A request is a message from the address "noreply@googlegroups.com"
    # with an "X-Google-Loop: unsub_success" header.
    elif 'from' in message['headers'] and \
            message['headers']['from'][0] == "noreply@googlegroups.com" and \
            'x-google-loop' in message['headers'] and \
            message['headers']['x-google-loop'][0] == 'unsub_success':
        _handle_unsubscribe_confirmation_google_groups(message, list_id,
                                                       timestamp)

    # Mailman Step 2 (List Requests Confirmation) Detector
    # A request is a message with X-Mailman-Version and X-List-Administrivia
    # headers (the latter set to "yes") with a Reply-To header that contains
    # the string "-confirm+".
    # TODO: find a way to identify a request with greater certainty.
    elif 'x-mailman-version' in message['headers'] \
            and 'x-list-administrivia' in message['headers'] \
            and message['headers']['x-list-administrivia'][0] == "yes" \
            and 'reply-to' in message['headers'] \
            and re.search('-confirm\+', message['headers']['reply-to'][0]):
        _handle_unsubscribe_confirm_request_mailman(message, list_id)

    # Mailman Step 3 (User is Unsubscribed) Detector
    # A request is a message with X-Mailman-Version and X-List-Administrivia
    # headers (the latter set to "yes").
    # TODO: find a way to identify a request with greater certainty.
    elif 'x-mailman-version' in message['headers'] \
            and 'x-list-administrivia' in message['headers'] \
            and message['headers']['x-list-administrivia'][0] == "yes":
        _handle_unsubscribe_confirmation_mailman(message, list_id, timestamp)
