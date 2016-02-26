#!/usr/bin/env python
"""
usage: sprint.py [--db <db>] [--pretend <date>] [<command>] [<args>...]

Options:
    --db <db>         Where to find the sqlite db.
    --pretend <date>  Pretend today is date

Commands:
    which             Show dates or previous, current, next sprints
    show              Show status of current sprint
    finish            Finish the last sprint
    prepare           Prepare for the current sprint
    start             Start the current sprint
    report SPRINT_ID  Show report on the given sprint ID
    backup            Backup the sprint state database

"""

import datetime
import os
import shutil
import sqlite3

from bson import ObjectId
from docopt import docopt

from ns1trellobase import NS1Base
from trello import Board

# snapshot phases
START = 1
FINISH = 2


class Sprint(NS1Base):

    # roadmap https://trello.com/b/HNjbGF0O
    SPRINT_RM_BOARD_ID = '56746d07d270ded2a04eb52c'

    def __init__(self, dbname):
        super(Sprint, self).__init__()
        self._db = None
        self._db_name = dbname
        self.today = None
        self.last_sprint_start = None
        self.next_sprint_start = None
        self.cur_sprint_start = None
        self.last_sprint_id = None
        self.next_sprint_id = None
        self.cur_sprint_id = None
        self.date_pretend = None
        self.list_ids = {}
        self.list_names_by_id = {}

    def boot(self):
        super(Sprint, self).boot()
        self.determine_sprint(self.date_pretend)
        self._db = sqlite3.connect(self._db_name)
        self.create_tables()
        self.populate_tables()

    def create_tables(self):
        c = self._db.cursor()
        c.execute('''create table if not exists version (version text primary key)''')
        c.execute('''create table if not exists lists (list_id text primary key, name text)''')
        c.execute('''create table if not exists cards (card_id text primary key, create_date text, '''
                  '''sprint_add_date text, due_date text, labels text, name text)''')
        c.execute('''create table if not exists sprints (sprint_id text primary key, start_date text, '''
                  '''end_date text, started integer, prepared integer, finished integer)''')
        c.execute('''create table if not exists sprint_state (sprint_id text, list_id text, card_id text,'''
                  ''' snapshot_phase integer, from_roadmap integer)''')
        c.execute('''create unique index if not exists sprint_idx on sprint_state (sprint_id, list_id, '''
                  '''card_id, snapshot_phase)''')
        self._db.commit()
        c.close()

    def populate_tables(self):
        c = self._db.cursor()
        # version the db
        c.execute('insert or replace into version values (1)')
        # ensure we have all the lists
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        lists = board.open_lists()
        for l in lists:
            c.execute('''insert or replace into lists values (?, ?)''', (l.id, l.name))
            self.list_ids[l.name] = l.id
            self.list_names_by_id[l.id] = l.name
        # make sure this and next sprint are in sprints table
        c.execute('''insert or ignore into sprints values (?, ?, ?, 0, 0, 0)''',
                  (self.cur_sprint_id,
                   self.cur_sprint_start,
                   self.next_sprint_start -
                   datetime.timedelta(days=1)))
        c.execute('''insert or ignore into sprints values (?, ?, ?, 0, 0, 0)''',
                  (self.next_sprint_id,
                   self.next_sprint_start,
                   self.next_weekday(self.next_sprint_start, 0)))
        self._db.commit()
        c.close()

    # http://stackoverflow.com/questions/6558535/python-find-the-date-for-the-first-monday-after-a-given-a-date
    def next_weekday(self, d, weekday):
        days_ahead = weekday - d.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return d + datetime.timedelta(days_ahead)

    def determine_sprint(self, override=None):
        if override:
            self.today = datetime.datetime.strptime(override, "%Y-%m-%d")
        else:
            self.today = datetime.datetime.today()
        if self.today.weekday() == 1:
            # today is a tue
            self.cur_sprint_start = self.today
        else:
            self.cur_sprint_start = self.next_weekday(self.today - datetime.timedelta(days=8), 1)

        self.next_sprint_start = self.next_weekday(self.today, 1)
        self.last_sprint_start = self.next_weekday(self.cur_sprint_start - datetime.timedelta(days=8), 1)
        self.last_sprint_id = str(self.last_sprint_start.date())
        self.next_sprint_id = str(self.next_sprint_start.date())
        self.cur_sprint_id = str(self.cur_sprint_start.date())

    def show(self):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        lists = board.open_lists()
        list_map = {}
        for l in lists:
            cards = l.list_cards()
            list_map[l.name] = [c.name for c in cards]
        print list_map

    def write_card(self, card):
        card.fetch()
        # pprint.pprint(vars(card))
        c = self._db.cursor()
        labels = [l.name for l in card.labels]
        create_date = ObjectId(card.id).generation_time
        c.execute('''insert or ignore into cards values (?, ?, ?, ?, ?, ?)''',
                  (card.id, create_date, self.today.isoformat(' '), card.due_date, ','.join(labels), card.name))
        c.close()

    def capture_sprint(self, sprint_id, snapshot_phase):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        cards = board.open_cards()
        c = self._db.cursor()
        # make sure cards exist
        for card in cards:
            self.write_card(card)
            # write them to state
            c.execute('''insert or ignore into sprint_state values (?, ?, ?, ?, ?)''',
                      (sprint_id, card.list_id, card.id, snapshot_phase, 0))
        c.close()

    def get_sprint_flag(self, name, sprint_id):
        c = self._db.cursor()
        c.execute('''select %s from sprints where sprint_id=?''' % name, (sprint_id,))
        flag = c.fetchone()
        if flag is None:
            raise Exception('Unable to get %s from %s' % (name, sprint_id))
        c.close()
        return flag[0]

    def set_sprint_flag(self, name, sprint_id):
        c = self._db.cursor()
        c.execute('''update sprints set %s=1 where sprint_id=?''' % name, (sprint_id,))
        c.close()

    def ensure(self, name, sprint_id):
        flag = self.get_sprint_flag(name, sprint_id)
        if int(flag) != 1:
            raise Exception("Sprint %s has not yet been %s, aborting" % (sprint_id, name))

    def ensure_not(self, name, sprint_id):
        flag = self.get_sprint_flag(name, sprint_id)
        if int(flag) == 1:
            raise Exception("Sprint %s has already been %s, aborting" % (sprint_id, name))

    def finish_sprint(self):

        print "Finishing Sprint %s" % self.last_sprint_id

        self.ensure('prepared', self.last_sprint_id)
        self.ensure('started', self.last_sprint_id)
        self.ensure_not('finished', self.last_sprint_id)

        # outgoing sprint: snapshot_phase=2 (finish)
        try:
            self.capture_sprint(self.last_sprint_id, snapshot_phase=FINISH)
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e
        self.set_sprint_flag('finished', self.last_sprint_id)
        self._db.commit()

        # archive all cards in Done column
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        done_list = board.get_list(self.list_ids['Done'])
        done_list.archive_all_cards()
        # done_cards = done_list.list_cards()
        # for card in done_cards:
        #     if not card.closed:
        #         print "Closing Done ticket: %s" % card.name
        #         card.set_closed(True)


    def prep_sprint(self):
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=1
        print "Preparing Sprint %s" % self.cur_sprint_id

        self.ensure_not('prepared', self.cur_sprint_id)

        ## change title to todays date
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        # no method for setting name, use client directly
        board.client.fetch_json(
            '/boards/' + board.id + '/name',
            http_method='PUT',
            post_args={'value': 'Current Sprint %s' % self.cur_sprint_id, }, )

        ## right shift sprint roadmap, bring into current sprint
        rm_board = Board(self.client, board_id=self.SPRINT_RM_BOARD_ID)
        rm_lists = rm_board.open_lists()
        rm_list_map = {l.name: l.id for l in rm_lists}
        from_rm_cards = []
        for l in reversed(rm_lists):
            if l.name == 'S + 1':
                # capture this card list so we can mark from_roadmap correctly
                from_rm_cards = l.list_cards()
                # send to sprint
                board_id = self.SPRINT_BOARD_ID
                list_id = self.list_ids['New']
            else:
                # send to next col
                board_id = self.SPRINT_RM_BOARD_ID
                n_id = int(l.name[-1:])
                list_id = rm_list_map['S + %s' % str(n_id-1)]
            l.client.fetch_json(
                '/lists/' + l.id + '/moveAllCards',
                post_args={'idBoard': board_id, 'idList': list_id},
                http_method='POST')

        ## capture tickets coming in from roadmap (so we can figure out which were added ad hoc after sprint start)
        c = self._db.cursor()
        try:
            for card in from_rm_cards:
                card.fetch(True)
                self.write_card(card)
                # write them to state
                c.execute('''insert into sprint_state values (?, ?, ?, ?, ?)''',
                          (self.cur_sprint_id, card.list_id, card.id, 1, 1))
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e

        c.close()

        self.set_sprint_flag('prepared', self.cur_sprint_id)
        self._db.commit()

    def start_sprint(self):
        print "Starting Sprint %s" % self.cur_sprint_id

        self.ensure('prepared', self.cur_sprint_id)
        self.ensure_not('started', self.cur_sprint_id)
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=0
        ## run after prep and after any manual tickets have been added, to capture sprint start
        ## capture sprint board state to sqlite (start)
        try:
            self.capture_sprint(self.cur_sprint_id, snapshot_phase=START)
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e

        self.set_sprint_flag('started', self.cur_sprint_id)
        self._db.commit()

    def backup(self):
        # send to s3
        shutil.copy(self._db_name, "%s.bak" % (self._db_name))

    def _report_count(self, sql, *args, **kwargs):
        c = self._db.cursor()
        r = c.execute(sql, *args, **kwargs)
        result = r.fetchall()
        c.close()
        return result[0][0]

    def _get_card_map(self, sprint_id, phase):
        c = self._db.cursor()
        sql = '''select card_id, list_id from sprint_state where snapshot_phase=? and sprint_id=?'''
        r = c.execute(sql, (phase, sprint_id, ))
        # list_id => [card_id, ...]
        map = {}
        for rec in r.fetchall():
            lname = self.list_names_by_id[rec[1]]
            if lname not in map:
                map[lname] = []
            map[lname].append(rec[0])
        c.close()
        return map

    def _array_marks(self, arr):
        quoted = ['"%s"' % v for v in arr]
        return ','.join(quoted)

    def report(self, sprint_id):
        print "Sprint Report %s (compared to previous %s)" % (sprint_id, self.last_sprint_id)

        c = self._db.cursor()

        # get a list of card ids from all the lists from last sprint finish, so we can see how they changed
        # (or not) to this sprint
        last_finish_map = self._get_card_map(self.last_sprint_id, FINISH)

        # for l in self.list_ids:
        #     print l
        #     print last_finish_map[self.list_ids[l]]

        # incoming: new to this sprint

        ### num incoming from sprint roadmaps (excluding cards carried over form last sprint)
        sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=1 and
                 from_roadmap=1 and list_id=? and cards.card_id=sprint_state.card_id
                 and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map['New']))
        print "Incoming From Sprint Roadmap"
        print self._report_count(sql, (sprint_id, self.list_ids['New']))

        ### num added to New column after Prep (after incoming from roadmap) but before Start
        sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=1 and
                 from_roadmap=0 and list_id=? and cards.card_id=sprint_state.card_id
                 and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map['New']))
        print "Incoming Ad Hoc"
        print self._report_count(sql, (sprint_id, self.list_ids['New']))

        ### total new at start
        sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=1 and
                 list_id=? and cards.card_id=sprint_state.card_id
                 and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map['New']))
        print "Total New At Start Of Sprint"
        print self._report_count(sql, (sprint_id, self.list_ids['New']))

        # incoming: punted/existed in last sprint
        ### num punted from last sprint in various columns
        punt_cols = ['New', 'In Progress', 'Review', 'Pending']
        punt_counts = 0
        for pc in punt_cols:
            sql = '''select count(*) from sprint_state where sprint_id=? and snapshot_phase=1 and
                     list_id=? and sprint_state.card_id in (%s)''' % (self._array_marks(last_finish_map[pc]))
            print "Punted From Last Sprint: %s" % pc
            rc = self._report_count(sql, (sprint_id, self.list_ids[pc]))
            punt_counts += int(rc)
            print rc

        print "Total Punted: %s (XX %%)" % (punt_counts)

        return

        # outgoing
        ### num in each column
        r = c.execute('''select lists.name, count(*) from sprint_state, lists where '''
                      '''sprint_state.list_id=lists.list_id and sprint_id=? and '''
                      '''snapshot_phase=2 group by lists.list_id''', (sprint_id, ))
        print "Ticket Outcome:"
        print r.fetchall()
        ### num overdue
        r = c.execute('''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=2 and '''
                      '''list_id!=? and cards.card_id=sprint_state.card_id and '''
                      '''datetime(due_date) < datetime("now")''', (sprint_id, self.list_ids['Done']))
        print "Number Overdue"
        print r.fetchall()

        ### avg overdue age of overdue tickets
        ### avg age of open tickets
        ### avg length in sprint
        ### num fires (label)
        ### num offense (label)
        ### num defense (label)



if __name__ == "__main__":

    args = docopt(__doc__)
    # print args

    if args['<command>'] is None:
        args['<command>'] = 'which'

    if args['--db'] is None:
        args['--db'] = os.getenv('HOME') + '/.ns1sprint.db'

    t = Sprint(args['--db'])
    if args['--pretend']:
        t.date_pretend = args['--pretend']
    t.boot()

    if args['<command>'] == 'which':
        print "Today is: %s, Current Sprint is: %s, Next Sprint is %s, Last Sprint is: %s" % \
              (t.today.date(), t.cur_sprint_id, t.next_sprint_id, t.last_sprint_id)
    elif args['<command>'] == 'show':
        t.show()
    elif args['<command>'] == 'finish':
        t.finish_sprint()
    elif args['<command>'] == 'prepare':
        t.prep_sprint()
    elif args['<command>'] == 'start':
        t.start_sprint()
    elif args['<command>'] == 'backup':
        t.backup()
    elif args['<command>'] == 'report':
        if len(args['<args>']) == 0:
            raise Exception('report requires a sprint id to report on')
        # pretend it's the sprint id they requested, so that last_sprint gets set properly
        t.date_pretend = args['<args>'][0]
        t.report(args['<args>'][0])
    else:
        print "unknown command: %s" % args['<command>']


