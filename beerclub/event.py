"Event: purchase, payment, etc."

import logging

import tornado.web

from . import constants
from . import settings
from . import utils
from .requesthandler import RequestHandler, ApiMixin
from .saver import Saver


class EventSaver(Saver):
    doctype = constants.EVENT

    def set(self, data):
        action = data.get('action')
        if action == constants.PURCHASE:
            self.set_purchase(**data)
        elif action == constants.PAYMENT:
            self.set_payment(**data)
        else:
            raise ValueError('invalid action')

    def set_purchase(self, **kwargs):
        self['action'] = constants.PURCHASE
        pid = kwargs.get('purchase')
        for purchase in settings['PURCHASE']:
            if pid == purchase['identifier']: break
        else:
            raise ValueError("no such purchase %s" % pid)
        bid = kwargs.get('beverage')
        for beverage in settings['BEVERAGE']:
            if bid == beverage['identifier']: break
        else:
            raise ValueError("no such beverage %s" % bid)
        self['beverage']    = beverage['identifier']
        self['description'] = purchase['identifier']
        if purchase['change']:
            self['credit'] = - beverage['price']
        else:
            self['credit'] = 0.0
        self.message = "You purchased one %s." % beverage['label']

    def set_payment(self, **kwargs):
        self['action'] = constants.PAYMENT
        try:
            amount = float(kwargs['amount'])
        except (KeyError, ValueError, TypeError):
            amount = 0.0
        pid = kwargs.get('payment')
        if pid == constants.EXPENDITURE:
            self['description'] = "%s: %s" % (constants.EXPENDITURE,
                                              kwargs.get('description'))
            self['credit'] = - amount
        else:
            for payment in settings['PAYMENT']:
                if pid == payment['identifier']: break
            else:
                raise ValueError("no such payment %s" % pid)
            self['description'] = payment['identifier']
            self['credit'] = amount
        self['date'] = kwargs.get('date', utils.today())


class Event(RequestHandler):
    "View an event; purchase, payment, etc. Admin may delete it."

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

    @tornado.web.authenticated
    def post(self, iuid):
        "Delete the event."
        self.check_admin()
        event = self.get_doc(iuid)
        if self.get_argument('_http_method', None) == 'DELETE':
            self.db.delete(event)
        self.see_other('account', event['member'])


class Purchase(RequestHandler):
    "Buying one beverage. Always by the currently logged in member."

    @tornado.web.authenticated
    def post(self):
        try:
            with EventSaver(rqh=self) as saver:
                saver['member']   = self.current_user['email']
                saver.set_purchase(purchase=self.get_argument('purchase',None),
                                   beverage=self.get_argument('beverage',None))
        except ValueError as error:
            self.set_error_flash(str(error))
        else:
            self.set_message_flash(saver.message)
        self.see_other('home')


class Payment(RequestHandler):
    "Payment to increase the credit of a member."

    @tornado.web.authenticated
    def get(self, email):
        self.check_admin()
        try:
            member = self.get_member(email, check=True)
        except KeyError:
            self.see_other('home')
        else:
            self.render('payment.html', member=member)

    @tornado.web.authenticated
    def post(self, email):
        self.check_admin()
        try:
            member = self.get_member(email, check=True)
        except KeyError:
            self.see_other('home')
            return
        try:
            with EventSaver(rqh=self) as saver:
                saver['member'] = member['email']
                saver.set_payment(payment=self.get_argument('payment', None),
                                  amount=self.get_argument('amount', None),
                                  date=self.get_argument('date',utils.today()))
        except ValueError as error:
            self.set_error_flash(str(error))
        self.see_other('account', member['email'])

        
class Expenditure(RequestHandler):
    "Expenditure that reduces the credit of the BeerClub master virtual member."

    @tornado.web.authenticated
    def get(self):
        self.check_admin()
        self.render('expenditure.html')

    @tornado.web.authenticated
    def post(self):
        self.check_admin()
        try:
            with EventSaver(rqh=self) as saver:
                saver['member'] = constants.BEERCLUB
                saver.set_payment(
                    payment=constants.EXPENDITURE,
                    amount=self.get_argument('amount', None),
                    description=self.get_argument('description', None),
                    date=self.get_argument('date', utils.today()))
        except ValueError as error:
            self.set_error_flash(str(error))
        self.see_other('payments')


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
        member['count'] = self.get_count(member)
        try:
            from_ = self.get_argument('from')
        except tornado.web.MissingArgumentError:
            from_ = utils.today(-settings['DISPLAY_ACCOUNT_DAYS'])
        try:
            to = self.get_argument('to')
        except tornado.web.MissingArgumentError:
            to = utils.today()
        if from_ > to:
            events = []
        else:
            events = self.get_docs('event/member',
                                   key=[member['email'], from_],
                                   last=[member['email'], to+constants.CEILING])
        self.render('account.html',
                    member=member, events=events, from_=from_, to=to)


class Activity(RequestHandler):
    "Members having made credit-affecting purchases recently."

    @tornado.web.authenticated
    def get(self):
        self.check_admin()
        activity = dict()
        from_ = utils.today(-settings['DISPLAY_ACTIVITY_DAYS'])
        to = utils.today()
        view = self.db.view('event/activity')
        for row in view[from_ : to+constants.CEILING]:
            try:
                activity[row.value] = max(activity[row.value], row.key)
            except KeyError:
                activity[row.value] = row.key
        activity.pop(constants.BEERCLUB, None)
        activity = activity.items()
        activity.sort(key=lambda i: i[1])
        # This is more efficient than calling for each member.
        all_members = self.get_docs('member/email')
        lookup = {}
        for member in all_members:
            lookup[member['email']] = member
        members = []
        for email, timestamp in activity:
            member = lookup[email]
            member['activity'] = timestamp
            members.append(member)
        utils.get_balances(self.db, members)
        self.render('activity.html', members=members)


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
        if from_ > to:
            events = []
        else:
            events = self.get_docs('event/ledger',
                                   key=from_,
                                   last=to+constants.CEILING)
        self.render('ledger.html',
                    beerclub_balance=self.get_beerclub_balance(),
                    members_balance=self.get_balance(),
                    events=events,
                    from_=from_,
                    to=to)


class Payments(RequestHandler):
    "Page for listing recent payment events, and the Beer Club balance."

    @tornado.web.authenticated
    def get(self):
        "Display recent payment events."
        try:
            from_ = self.get_argument('from')
        except tornado.web.MissingArgumentError:
            from_ = utils.today(-settings['DISPLAY_PAYMENT_DAYS'])
        try:
            to = self.get_argument('to')
        except tornado.web.MissingArgumentError:
            to = utils.today()
        if from_ > to:
            events = []
        else:
            events = self.get_docs('event/payment',
                                   key=from_,
                                   last=to+constants.CEILING)
        self.render('payments.html', events=events, from_=from_, to=to)


class EventApiV1(ApiMixin, RequestHandler):
    "Return event data."

    @tornado.web.authenticated
    def get(self, iuid):
        self.check_admin()
        event = self.get_doc(iuid)
        if event.get(constants.DOCTYPE) != constants.EVENT:
            raise tornado.web.HTTPError(404, reason='no such event')
        data = dict(iuid=event['_id'])
        for key in ['action', 'beverage', 'credit',
                    'date', 'description', 'log']:
            data[key] = event.get(key)
        self.write(data)


class MemberEventApiV1(ApiMixin, RequestHandler):
    "Add an event for the member."

    @tornado.web.authenticated
    def post(self, email):
        self.check_admin()
        try:
            member = self.get_member(email)
        except KeyError:
            raise tornado.web.HTTPError(404, reason='no such member')
        try:
            with EventSaver(rqh=self) as saver:
                saver['member'] = member['email']
                saver.set(self.get_json_body())
        except ValueError as error:
            raise tornado.web.HTTPError(400, reason=str(error))
        self.write(dict(iuid=saver.doc['_id']))
