"Send launch message email to all members; regardless of status."

from __future__ import print_function

import time

from beerclub import utils


EMAIL_PAUSE = 3.0
EMAIL_SUBJECT_TEXT = "New SciLifeLab Beer Club system"
EMAIL_MESSAGE_TEXT = """Hello {name},

Today a new system for the Beer Club is launched.

To purchase beers in the SciLifeLab Pub, one must have an account
in the new system. If you receive this email, then you already
have an account in it.

You will soon receive another email with info on how to set the
password for your member account.

The old paper list system is hereby scrapped. Your credit balance
has been transferred to the new system.

*NOTE*: All purchases, without exception, even when you pay cash
directly, must be recorded in the new system.

The new system is web-based and has been designed to look and
behave similar to a smartphone app.

https://beerclub.scilifelab.se/

Any questions? Ask me.

Yours sincerely,

Per Kraulis
SciLifeLab Beer Club administrator
"""

def send_launch_message(db):
    "Send launch message to all members."
    view = db.view('member/email')
    emailserver = utils.EmailServer()
    for row in view:
        member = utils.get_member(db, row.key)
        name = u"{} {}".format(member['first_name'], member['last_name'])
        message = EMAIL_MESSAGE_TEXT.format(name=name)
        emailserver.send(member['email'],
                         EMAIL_SUBJECT_TEXT,
                         message)
        time.sleep(EMAIL_PAUSE)


if __name__ == "__main__":
    utils.setup()
    utils.initialize()
    send_launch_message(utils.get_db())