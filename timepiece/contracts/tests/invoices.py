import datetime
import random
import urllib

from django.contrib.auth.models import User, Permission
from django.core.urlresolvers import reverse

from timepiece import utils
from timepiece.forms import DATE_FORM_FORMAT
from timepiece.tests.base import TimepieceDataTestCase

from timepiece.contracts.models import EntryGroup, HourGroup
from timepiece.entries.models import Activity, Entry


class InvoiceViewPreviousTestCase(TimepieceDataTestCase):

    def setUp(self):
        super(InvoiceViewPreviousTestCase, self).setUp()
        self.user.is_superuser = True
        self.user.save()
        self.client.login(username=self.user.username, password='abc')
        # Make some projects and entries for invoice creation
        self.project = self.create_project(billable=True)
        self.project2 = self.create_project(billable=True)
        last_start = self.log_many([self.project, self.project2])
        # Add some non-billable entries
        self.log_many([self.project, self.project2], start=last_start,
                      billable=False)
        self.create_invoice(self.project, {'static': 'invoiced'})
        self.create_invoice(self.project2, {'status': 'not-invoiced'})

    def get_create_url(self, **kwargs):
        base_url = reverse('create_invoice')
        params = urllib.urlencode(kwargs)
        return '{0}?{1}'.format(base_url, params)

    def log_many(self, projects, num_entries=20, start=None, billable=True):
        start = utils.add_timezone(datetime.datetime(2011, 1, 1, 0, 0, 0))
        for index in xrange(0, num_entries):
            start += datetime.timedelta(hours=(5 * index))
            project = projects[index % len(projects)]  # Alternate projects
            self.log_time(start=start, status='approved', project=project,
                          billable=billable)
        return start

    def create_invoice(self, project=None, data=None):
        data = data or {}
        if not project:
            project = self.project
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31))
        url = self.get_create_url(project=project.id, to_date=to_date.strftime('%Y-%m-%d'))
        params = {
            'number': str(random.randint(999, 9999)),
            'status': 'invoiced',
        }
        params.update(data)
        response = self.client.post(url, params)

    def get_invoice(self):
        invoices = EntryGroup.objects.all()
        return random.choice(invoices)

    def get_entry(self, invoice):
        entries = invoice.entries.all()
        return random.choice(entries)

    def test_previous_invoice_list_no_search(self):
        url = reverse('list_invoices')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        invoices = response.context['invoices']
        self.assertEqual(len(invoices), 2)

    def test_previous_invoice_list_search(self):

        def search(query):
            response = self.client.get(list_url, data={'search': query})
            return response.context['invoices']

        list_url = reverse('list_invoices')
        project3 = self.create_project(billable=True, data={'name': ':-D'})
        self.log_many([project3], 10)
        self.create_invoice(project3, data={'status': 'invoiced',
                'comments': 'comment!', 'number': '###'})

        # Search comments, project name, and number.
        for query in ['comment!', ':-D', '###']:
            results = search(query)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].project, project3)

        # Search in username
        results = search(self.user.username)
        self.assertEqual(len(results), 3)  # all were created by this user

        # No results
        results = search("You won't find me here")
        self.assertEquals(len(results), 0)

    def test_invoice_detail(self):
        invoices = EntryGroup.objects.all()
        for invoice in invoices:
            url = reverse('view_invoice', args=[invoice.id])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['invoice'])

    def test_invoice_csv(self):
        invoice = self.get_invoice()
        url = reverse('view_invoice_csv', args=[invoice.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = dict(response.items())
        self.assertEqual(data['Content-Type'], 'text/csv')
        disposition = data['Content-Disposition']
        self.assertTrue(disposition.startswith('attachment; filename=Invoice'))
        contents = response.content.splitlines()
        # TODO: Possibly find a meaningful way to test contents
        # Pull off header line and totals line
        header = contents.pop(0)
        total = contents.pop()
        num_entries = invoice.entries.all().count()
        self.assertEqual(num_entries, len(contents))

    def test_invoice_csv_bad_id(self):
        url = reverse('view_invoice_csv', args=[9999999999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_invoice_edit_get(self):
        invoice = self.get_invoice()
        url = reverse('edit_invoice', args=[invoice.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['invoice'].id, invoice.id)
        self.assertTrue(response.context['entries'])

    def test_invoice_edit_bad_id(self):
        url = reverse('edit_invoice', args=[99999999999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_invoice_edit_post(self):
        invoice = self.get_invoice()
        url = reverse('edit_invoice', args=(invoice.id,))
        status = 'invoiced' if invoice.status != 'invoiced' else 'not-invoiced'
        params = {
            'number': int(invoice.number) + 1,
            'status': status,
            'comments': 'Comments',
        }
        response = self.client.post(url, params)
        self.assertEqual(response.status_code, 302)
        new_invoice = EntryGroup.objects.get(pk=invoice.id)
        self.assertEqual(int(invoice.number) + 1, int(new_invoice.number))
        self.assertTrue(invoice.status != new_invoice.status)
        self.assertEqual(new_invoice.comments, 'Comments')

    def test_invoice_edit_bad_post(self):
        invoice = self.get_invoice()
        url = reverse('edit_invoice', args=[invoice.id])
        params = {
            'number': '2',
            'status': 'not_in_choices',
        }
        response = self.client.post(url, params)
        err_msg = 'Select a valid choice. not_in_choices is not one of ' + \
                  'the available choices.'
        self.assertFormError(response, 'invoice_form', 'status', err_msg)

    def test_invoice_delete_get(self):
        invoice = self.get_invoice()
        url = reverse('delete_invoice', args=[invoice.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_invoice_delete(self):
        invoice = self.get_invoice()
        entry_ids = [entry.pk for entry in invoice.entries.all()]
        url = reverse('delete_invoice', args=[invoice.id])
        response = self.client.post(url, {'delete': 'delete'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EntryGroup.objects.filter(pk=invoice.id))
        entries = Entry.objects.filter(pk__in=entry_ids)
        for entry in entries:
            self.assertEqual(entry.status, 'approved')

    def test_invoice_delete_cancel(self):
        invoice = self.get_invoice()
        url = reverse('delete_invoice', args=[invoice.id])
        response = self.client.post(url, {'cancel': 'cancel'})
        self.assertEqual(response.status_code, 302)
        # Canceled out so the invoice was not deleted
        self.assertTrue(EntryGroup.objects.get(pk=invoice.id))

    def test_invoice_delete_bad_args(self):
        invoice = self.get_invoice()
        entry_ids = [entry.pk for entry in invoice.entries.all()]
        url = reverse('delete_invoice', args=[1232345345])
        response = self.client.post(url, {'delete': 'delete'})
        self.assertEqual(response.status_code, 404)

    def test_rm_invoice_entry_get(self):
        invoice = self.get_invoice()
        entry = self.get_entry(invoice)
        url = reverse('delete_invoice_entry', args=[invoice.id, entry.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['invoice'], invoice)
        self.assertEqual(response.context['entry'], entry)

    def test_rm_invoice_entry_get_bad_id(self):
        invoice = self.get_invoice()
        entry = self.get_entry(invoice)
        url = reverse('delete_invoice_entry', args=[invoice.id, 999999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        url = reverse('delete_invoice_entry', args=[9999, entry.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_rm_invoice_entry_post(self):
        invoice = self.get_invoice()
        entry = self.get_entry(invoice)
        url = reverse('delete_invoice_entry', args=[invoice.id, entry.id])
        response = self.client.post(url, {'submit': ''})
        self.assertEqual(response.status_code, 302)
        new_invoice = EntryGroup.objects.get(pk=invoice.pk)
        rm_entry = new_invoice.entries.filter(pk=entry.id)
        self.assertFalse(rm_entry)
        new_entry = Entry.objects.get(pk=entry.pk)
        self.assertEqual(new_entry.status, 'approved')
        self.assertEqual(new_entry.entry_group, None)


class InvoiceCreateTestCase(TimepieceDataTestCase):

    def setUp(self):
        super(InvoiceCreateTestCase, self).setUp()
        self.user.is_superuser = True
        self.user.save()
        self.client.login(username=self.user.username, password='abc')
        start = utils.add_timezone(datetime.datetime(2011, 1, 1, 8))
        end = utils.add_timezone(datetime.datetime(2011, 1, 1, 12))
        self.project_billable = self.create_project(billable=True)
        self.project_billable2 = self.create_project(billable=True)
        self.project_non_billable = self.create_project(billable=False)
        self.entry1 = self.create_entry({
            'user': self.user,
            'project': self.project_billable,
            'activity': self.create_activity(data={'billable': True}),
            'start_time': start,
            'end_time': end,
            'status': 'approved',
        })
        self.entry2 = self.create_entry({
            'user': self.user,
            'project': self.project_billable,
            'activity': self.create_activity(data={'billable': True}),
            'start_time': start - datetime.timedelta(days=5),
            'end_time': end - datetime.timedelta(days=5),
            'status': 'approved',
        })
        self.entry3 = self.create_entry({
            'user': self.user,
            'project': self.project_billable2,
            'activity': self.create_activity(data={'billable': False}),
            'start_time': start - datetime.timedelta(days=10),
            'end_time': end - datetime.timedelta(days=10),
            'status': 'approved',
        })
        self.entry4 = self.create_entry({
            'user': self.user,
            'project': self.project_non_billable,
            'start_time': start + datetime.timedelta(hours=11),
            'end_time': end + datetime.timedelta(hours=15),
            'status': 'approved',
        })

    def get_create_url(self, **kwargs):
        base_url = reverse('create_invoice')
        params = urllib.urlencode(kwargs)
        return '{0}?{1}'.format(base_url, params)

    def make_hourgroups(self):
        """
        Make several hour groups, one for each activity, and one that contains
        all activities to check for hour groups with multiple activities.
        """
        all_activities = Activity.objects.all()
        for activity in all_activities:
            hg = HourGroup.objects.create(name=activity.name)
            hg.activities.add(activity)

    def login_with_permission(self):
        """Helper to login as user with correct permissions"""
        generate_invoice = Permission.objects.get(
            codename='generate_project_invoice')
        user = self.create_user('perm', 'e@e.com', 'abc',
                user_permissions=[generate_invoice])

    def test_invoice_create(self):
        """
        Verify that only billable projects appear on the create invoice and
        that the links have accurate date information
        """
        url = reverse('list_outstanding_invoices')
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31, 0, 0, 0))
        params = {'to_date': to_date.strftime(DATE_FORM_FORMAT)}
        response = self.client.get(url, params)
        # The number of projects should be 3 because entry4 has billable=False
        self.assertEquals(response.context['project_totals'].count(), 3)
        # Verify that the date on the mark as invoiced links will be correct
        to_date_str = response.context['to_date'].strftime('%Y %m %d')
        self.assertEquals(to_date_str, '2011 01 31')

    def test_invoice_create_requires_to(self):
        """Verify that create invoice links are blank without a to date"""
        url = reverse('list_outstanding_invoices')
        params = {'to_date': ''}
        response = self.client.get(url, params)
        # The number of projects should be 1 because entry3 has billable=False
        num_project_totals = len(response.context['project_totals'])
        self.assertEquals(num_project_totals, 0)

    def test_invoice_create_with_from(self):
        # Add another entry and make sure from filters it out
        url = reverse('list_outstanding_invoices')
        from_date = utils.add_timezone(datetime.datetime(2011, 1, 1, 0, 0, 0))
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31, 0, 0, 0))
        params = {
            'from_date': from_date.strftime(DATE_FORM_FORMAT),
            'to_date': to_date.strftime(DATE_FORM_FORMAT),
        }
        response = self.client.get(url, params)
        # From date filters out one entry
        num_project_totals = len(response.context['project_totals'])
        self.assertEquals(num_project_totals, 1)
        # Verify that the date on the mark as invoiced links will be correct
        from_date_str = response.context['from_date'].strftime('%Y %m %d')
        self.assertEquals(from_date_str, '2011 01 01')
        to_date_str = response.context['to_date'].strftime('%Y %m %d')
        self.assertEquals(to_date_str, '2011 01 31')

    def test_invoice_confirm_view_user(self):
        """A regular user should not be able to access this page"""
        self.client.login(username='user2', password='abc')
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31))
        url = self.get_create_url(project=self.project_billable.pk,
                to_date=to_date.strftime(DATE_FORM_FORMAT))

        response = self.client.get(url)
        self.assertEquals(response.status_code, 403)

    def test_invoice_confirm_view_permission(self):
        """
        If you have the correct permission, you should be
        able to create an invoice
        """
        self.login_with_permission()
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31))
        url = self.get_create_url(project=self.project_billable.pk,
                to_date=to_date.strftime(DATE_FORM_FORMAT))

        response = self.client.get(url)
        self.assertEquals(response.status_code, 200)

    def test_invoice_confirm_view(self):
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31))
        url = self.get_create_url(project=self.project_billable.pk,
                to_date=to_date.strftime(DATE_FORM_FORMAT))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        to_date_str = response.context['to_date'].strftime('%Y %m %d')
        self.assertEqual(to_date_str, '2011 01 31')
        # View can also take from date
        from_date = utils.add_timezone(datetime.datetime(2011, 1, 1))
        kwargs = {
            'project': self.project_billable.id,
            'to_date': to_date.strftime(DATE_FORM_FORMAT),
            'from_date': from_date.strftime(DATE_FORM_FORMAT),
        }
        url = self.get_create_url(**kwargs)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        from_date_str = response.context['from_date'].strftime('%Y %m %d')
        to_date_str = response.context['to_date'].strftime('%Y %m %d')
        self.assertEqual(from_date_str, '2011 01 01')
        self.assertEqual(to_date_str, '2011 01 31')

    def test_invoice_confirm_totals(self):
        """Verify that the per activity totals are valid."""
        # Make a few extra entries to test per activity totals
        start = utils.add_timezone(datetime.datetime(2011, 1, 1, 8))
        end = utils.add_timezone(datetime.datetime(2011, 1, 1, 12))
        # start = utils.add_timezone(datetime.datetime.now())
        # end = start + datetime.timedelta(hours=4)
        activity = self.create_activity(data={'name': 'activity1',
                                              'billable': True})
        for num in xrange(0, 4):
            new_entry = self.create_entry({
                'user': self.user,
                'project': self.project_billable,
                'start_time': start - datetime.timedelta(days=num),
                'end_time': end - datetime.timedelta(days=num),
                'status': 'approved',
                'activity': activity,
            })
        self.make_hourgroups()
        to_date = datetime.datetime(2011, 1, 31)
        kwargs = {
            'project': self.project_billable.id,
            'to_date': to_date.strftime(DATE_FORM_FORMAT),
        }
        url = self.get_create_url(**kwargs)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        for name, hours_activities in response.context['billable_totals']:
            total, activities = hours_activities
            if name == 'activity1':
                self.assertEqual(total, 16)
                self.assertEqual(total, activities[0][1])
                self.assertEqual(name, activities[0][0])
            elif name == 'Total':
                self.assertEqual(total, 24)
                self.assertEqual(activities, [])
            else:
                # Each other activity is 4 hrs each
                self.assertEqual(total, 4)
                self.assertEqual(total, activities[0][1])
                self.assertEqual(name, activities[0][0])

    def test_invoice_confirm_bad_args(self):
        # A year/month/project with no entries should raise a 404
        kwargs = {
            'project': self.project_billable.id,
            'to_date': '2008-01-13',
        }
        url = self.get_create_url(**kwargs)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        # A year/month with bad/overflow values should raise a 404
        kwargs = {
            'project': self.project_billable.id,
            'to_date': '9999-13-01',
        }
        url = self.get_create_url(**kwargs)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_make_invoice(self):
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31))
        kwargs = {
            'project': self.project_billable.id,
            'to_date': to_date.strftime(DATE_FORM_FORMAT),
        }
        url = self.get_create_url(**kwargs)
        response = self.client.post(url, {'number': '3', 'status': 'invoiced'})
        self.assertEqual(response.status_code, 302)
        # Verify an invoice was created with the correct attributes
        invoice = EntryGroup.objects.get(number=3)
        self.assertEqual(invoice.project.id, self.project_billable.id)
        self.assertEqual(invoice.start, None)
        self.assertEqual(invoice.end.strftime('%Y %m %d'), '2011 01 31')
        self.assertEqual(len(invoice.entries.all()), 2)
        # Verify that the entries were invoiced appropriately
        # and the unrelated entries were untouched
        entries = Entry.objects.all()
        invoiced = entries.filter(status='invoiced')
        for entry in invoiced:
            self.assertEqual(entry.entry_group_id, invoice.id)
        approved = entries.filter(status='approved')
        self.assertEqual(len(approved), 2)
        self.assertEqual(approved[0].entry_group_id, None)

    def test_make_invoice_with_from_uninvoiced(self):
        from_date = utils.add_timezone(datetime.datetime(2011, 1, 1))
        to_date = utils.add_timezone(datetime.datetime(2011, 1, 31))
        kwargs = {
            'project': self.project_billable.id,
            'to_date': to_date.strftime(DATE_FORM_FORMAT),
            'from_date': from_date.strftime(DATE_FORM_FORMAT),
        }
        url = self.get_create_url(**kwargs)
        response = self.client.post(url, {'number': '5',
                                          'status': 'not-invoiced'})
        self.assertEqual(response.status_code, 302)
        # Verify an invoice was created with the correct attributes
        invoice = EntryGroup.objects.get(number=5)
        self.assertEqual(invoice.project.id, self.project_billable.id)
        self.assertEqual(invoice.start.strftime('%Y %m %d'), '2011 01 01')
        self.assertEqual(invoice.end.strftime('%Y %m %d'), '2011 01 31')
        self.assertEqual(len(invoice.entries.all()), 1)
        # Verify that the entries were invoiced appropriately
        # and the unrelated entries were untouched
        entries = Entry.objects.all()
        uninvoiced = entries.filter(status='uninvoiced')
        for entry in uninvoiced:
            self.assertEqual(entry.entry_group_id, invoice.id)
