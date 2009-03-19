# This is an extension which converts a message/raw/email to a 'message'
import logging

logger = logging.getLogger(__name__)

from ...proc import base

class EmailConverter(base.ConverterBase):
    def convert(self, doc):
        # for now, the email repr has all we need.
        ret = doc.copy()
        for n in ret.keys():
            if n.startswith('_') or n.startswith('raindrop'):
                del ret[n]
        return ret
