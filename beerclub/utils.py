"Various supporting functions."

import datetime
import email.mime.text
import hashlib
import json
import logging
import smtplib
import string
import sys
import unicodedata
import urlparse
import uuid

import couchdb

import beerclub
from beerclub import constants
from beerclub import settings


def setup():
    "Setup: read settings, set logging."
    try:
        with open('settings.json') as infile:
            site = json.load(infile)
            settings.update(site)
    except IOError:
        pass
    if not settings['COOKIE_SECRET']:
        logging.error('variable COOKIE_SECRET not set')
        sys.exit(1)
    if not settings['PASSWORD_SALT']:
        logging.error('variable PASSWORD_SALT not set')
        sys.exit(1)
    if not settings['EMAIL']['HOST']:
        logging.error("email host EMAIL['HOST'] not defined")
        sys.exit(1)
    parts = urlparse.urlparse(settings['BASE_URL'])
    settings['PORT'] = parts.port or 80
    # Convert format specifiers in statements.
    settings['POLICY_STATEMENT'] = settings['POLICY_STATEMENT'].format(**settings)
    settings['PRIVACY_STATEMENT'] = settings['PRIVACY_STATEMENT'].format(**settings)
    # Set up logging
    if settings.get('LOGGING_DEBUG'):
        kwargs = dict(level=logging.DEBUG)
    else:
        kwargs = dict(level=logging.INFO)
    try:
        kwargs['format'] = settings['LOGGING_FORMAT']
    except KeyError:
        pass
    logging.basicConfig(**kwargs)
    logging.info("BeerClub version %s", beerclub.__version__)
    logging.info("ROOT_DIR: %s", settings['ROOT_DIR'])
    logging.info("logging debug: %s", settings['LOGGING_DEBUG'])

def get_dbserver():
    "Get the server connection, with credentials if any."
    server = couchdb.Server(settings['DATABASE_SERVER'])
    if settings.get('DATABASE_ACCOUNT') and settings.get('DATABASE_PASSWORD'):
        server.resource.credentials = (settings.get('DATABASE_ACCOUNT'),
                                       settings.get('DATABASE_PASSWORD'))
    return server

def get_db():
    "Return the handle for the CouchDB database."
    server = get_dbserver()
    try:
        return server[settings['DATABASE_NAME']]
    except couchdb.http.ResourceNotFound:
        raise KeyError("CouchDB database '%s' does not exist." % 
                       settings['DATABASE_NAME'])

def get_doc(db, key, viewname=None):
    """Get the document with the given i, or from the given view.
    Raise KeyError if not found.
    """
    if viewname is None:
        try:
            return db[key]
        except couchdb.ResourceNotFound:
            raise KeyError
    else:
        result = list(db.view(viewname, include_docs=True, reduce=False)[key])
        if len(result) != 1:
            raise KeyError("%i items found", len(result))
        return result[0].doc

def get_docs(db, viewname, key=None, last=None, **kwargs):
    """Get the list of documents using the named view and
    the given key or interval.
    """
    view = db.view(viewname, include_docs=True, reduce=False, **kwargs)
    if key is None:
        iterator = view
    elif last is None:
        iterator = view[key]
    else:
        iterator = view[key:last]
    return [i.doc for i in iterator]

def get_account(db, email):
    """Get the account identified by the email address.
    Raise KeyError if no such account.
    """
    try:
        doc = get_doc(db, email.strip().lower(), 'account/email')
    except KeyError:
        raise KeyError("no such account %s" % email)
    if doc[constants.DOCTYPE] != constants.ACCOUNT:
        raise KeyError("document %s is not an account" % email)
    return doc

def get_iuid():
    "Return a unique instance identifier."
    return uuid.uuid4().hex

def hashed_password(password):
    "Return the password in hashed form."
    sha256 = hashlib.sha256(settings['PASSWORD_SALT'])
    sha256.update(password)
    return sha256.hexdigest()

def check_password(password):
    """Check that the password is long and complex enough.
    Raise ValueError otherwise."""
    if len(password) < settings['MIN_PASSWORD_LENGTH']:
        raise ValueError("Password must be at least {0} characters.".
                         format(settings['MIN_PASSWORD_LENGTH']))

def timestamp(days=None):
    """Current date and time (UTC) in ISO format, with millisecond precision.
    Add the specified offset in days, if given.
    """
    instant = datetime.datetime.utcnow()
    if days:
        instant += datetime.timedelta(days=days)
    instant = instant.isoformat()
    return instant[:17] + "%06.3f" % float(instant[17:]) + "Z"

def today(days=None):
    """Current date (UTC) in ISO format.
    Add the specified offset in days, if given.
    """
    instant = datetime.datetime.utcnow()
    if days:
        instant += datetime.timedelta(days=days)
    result = instant.isoformat()
    return result[:result.index('T')]

def to_ascii(value):
    "Convert any non-ASCII character to its closest ASCII equivalent."
    if not isinstance(value, unicode):
        value = unicode(value, 'utf-8')
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')

def to_utf8(value):
    "Convert value to UTF-8 representation."
    if isinstance(value, basestring):
        if not isinstance(value, unicode):
            value = unicode(value, 'utf-8')
        return value.encode('utf-8')
    else:
        return value

def to_bool(value):
    "Convert the value into a boolean, interpreting various string values."
    if isinstance(value, bool): return value
    if not value: return False
    lowvalue = value.lower()
    if lowvalue in constants.TRUE: return True
    if lowvalue in constants.FALSE: return False
    raise ValueError("invalid boolean: '%s'" % value)

def normalize_phone(value):
    "Return normalized phone number. Get rid of all non-digits."
    return ''.join([c for c in value if c in string.digits])

class EmailServer(object):
    "A connection to an email server for sending emails."

    def __init__(self):
        """Open the connection to the email server.
        Raise ValueError if no email server host has been defined.
        """
        host = settings['EMAIL']['HOST']
        if not host:
            raise ValueError('no email server host defined')
        try:
            port = settings['EMAIL']['PORT']
        except KeyError:
            self.server = smtplib.SMTP(host)
        else:
            self.server = smtplib.SMTP(host, port=port)
        if settings['EMAIL'].get('TLS'):
            self.server.starttls()
        try:
            user = settings['EMAIL']['USER']
            password = settings['EMAIL']['PASSWORD']
        except KeyError:
            pass
        else:
            self.server.login(user, password)
        self.email = settings.get('SITE_EMAIL') or settings['EMAIL']['SENDER']

    def __del__(self):
        "Close the connection to the email server."
        try:
            self.server.quit()
        except AttributeError:
            pass

    def send(self, recipient, subject, text):
        "Send an email."
        mail = email.mime.text.MIMEText(text, 'plain', 'utf-8')
        mail['Subject'] = subject
        mail['From'] = self.email
        mail['To'] = recipient
        self.server.sendmail(self.email, [recipient], mail.as_string())
        logging.debug("Sent email to %s", recipient)
