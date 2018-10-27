"Event: payment, etc."

import logging

import tornado.web

from . import constants
from . import settings
from . import utils
from .requesthandler import RequestHandler
from .saver import Saver


class EventSaver(Saver):
    doctype = constants.EVENT


class Event(RequestHandler):
    "View an event; payment or other."

    @tornado.web.authenticated
    def get(self, iuid):
        event = self.get_doc(iuid)
        # View access privilege
        if not (self.is_admin() or
                event['member'] == self.current_user['email']):
            self.set_error_flash('You may not view the event data.')
            self.see_other('home')
            return
        self.render('event.html', event=event)


class Purchase(RequestHandler):
    "Buying one beverage. Always by the currently logged in member."

    @tornado.web.authenticated
    def post(self):
        bid =self.get_argument('beverage')
        for beverage in settings['BEVERAGE']:
            if bid == beverage['identifier']: break
        else:
            raise KeyError("no such beverage %s" % bid)
        pid =self.get_argument('payment')
        for payment in settings['PAYMENT']:
            if pid == payment['identifier']: break
        else:
            raise KeyError("no such payment %s" % pid)
        with EventSaver(rqh=self) as saver:
            saver['member']   = self.current_user['email']
            saver['action']   = constants.PURCHASE
            saver['beverage'] = beverage['identifier']
            saver['price']    = beverage['price']
            saver['payment']  = payment['identifier']
            if payment['change']:
                saver['credit'] = - beverage['price']
            else:
                saver['credit'] = 0
        self.set_message_flash("Your purchased one %s." % beverage['label'])
        self.see_other('home')


class Repayment(RequestHandler):
    "Repayment to increase the credit of a member."

    @tornado.web.authenticated
    def get(self, email):
        self.check_admin()
        try:
            member = self.get_member(email, check=True)
        except KeyError:
            self.see_other('home')
        else:
            self.render('repayment.html', member=member)

    @tornado.web.authenticated
    def post(self, email):
        self.check_admin()
        try:
            member = self.get_member(email, check=True)
        except KeyError:
            self.see_other('home')
            return
        pid =self.get_argument('payment')
        for payment in settings['REPAYMENT']:
            if pid == payment['identifier']: break
        else:
            raise KeyError("no such repayment %s" % pid)
        with EventSaver(rqh=self) as saver:
            saver['member']  = member['email']
            saver['action']  = constants.REPAYMENT
            saver['payment'] = payment['identifier']
            saver['credit']  = float(self.get_argument('amount'))
            saver['date']    = self.get_argument('date', utils.today())
        self.see_other('members')

        
class Expenditure(RequestHandler):
    "Expenditure that reduces the credit of the BeerClub master virtual member."

    @tornado.web.authenticated
    def get(self):
        self.check_admin()
        self.render('expenditure.html')

    @tornado.web.authenticated
    def post(self):
        self.check_admin()
        with EventSaver(rqh=self) as saver:
            saver['member'] = constants.BEERCLUB
            saver['action'] = constants.EXPENDITURE
            saver['credit'] = - float(self.get_argument('amount'))
            saver['date']   = self.get_argument('date', utils.today())
            saver['description'] = self.get_argument('description', None)
        self.see_other('ledger')


class Account(RequestHandler):
    "View events for a member account."

    @tornado.web.authenticated
    def get(self, email):
        try:
            member = self.get_member(email, check=True)
        except KeyError:
            self.see_other('home')
            return 
        member['balance'] = self.get_balance(member)
        try:
            from_ = self.get_argument('from')
        except tornado.web.MissingArgumentError:
            from_ = utils.today(-settings['DISPLAY_LEDGER_DAYS'])
        try:
            to = self.get_argument('to')
        except tornado.web.MissingArgumentError:
            to = utils.today()
        events = self.get_docs('event/member',
                               key=[member['email'], from_],
                               last=[member['email'], to + constants.CEILING])
        self.render('account.html',
                    member=member,
                    beverages_count=self.get_beverages_count(),
                    events=events, 
                    from_=from_,
                    to=to,
                    show_event_links=self.is_admin(),
                    show_member_col=self.is_admin())


class Active(RequestHandler):
    "Members having made credit-affecting purchases recently."

    @tornado.web.authenticated
    def get(self):
        self.check_admin()
        active = dict()
        from_ = utils.today(-settings['DISPLAY_ACTIVITY_DAYS'])
        to = utils.today()
        view = self.db.view('event/activity')
        for row in view[from_ : to+constants.CEILING]:
            try:
                active[row.value] = max(active[row.value], row.key)
            except KeyError:
                active[row.value] = row.key
        active.pop(constants.BEERCLUB, None)
        active = active.items()
        active.sort(key=lambda i: i[1])
        # This is more efficient than calling for each member.
        all_members = self.get_docs('member/email')
        lookup = {}
        for member in all_members:
            lookup[member['email']] = member
        members = []
        for email, timestamp in active:
            member = lookup[email]
            member['activity'] = timestamp
            members.append(member)
        utils.get_balances(self.db, members)
        self.render('active.html', members=members)


class Ledger(RequestHandler):
    "Ledger page for listing recent events."

    @tornado.web.authenticated
    def get(self):
        "Display recent events."
        try:
            from_ = self.get_argument('from')
        except tornado.web.MissingArgumentError:
            from_ = utils.today(-settings['DISPLAY_LEDGER_DAYS'])
        try:
            to = self.get_argument('to')
        except tornado.web.MissingArgumentError:
            to = utils.today()
        events = self.get_docs('event/ledger',
                               key=from_,
                               last=to+constants.CEILING)
        self.render('ledger.html',
                    balance=self.get_balance(),
                    events=events,
                    from_=from_,
                    to=to,
                    show_event_links=self.is_admin(),
                    show_member_col=self.is_admin())
