#!/usr/bin/env python
"""
usage: sprint.py [--db <db>] [--pretend <date>] [<command>] [<args>...]

Options:
    --db <db>         Where to find the sqlite db.
    --pretend <date>  Pretend today is date

Commands:
    show    Show status of current sprint

"""

import datetime
import os
import sqlite3

from bson import ObjectId
from docopt import docopt

from ns1trellobase import NS1Base
from trello import Board


class Sprint(NS1Base):

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

    def boot(self):
        super(Sprint, self).boot()
        self.determine_sprint(self.date_pretend)
        self._db = sqlite3.connect(self._db_name)
        self.create_tables()
        self.populate_tables()

    def create_tables(self):
        c = self._db.cursor()
        c.execute('''create table if not exists version (version text primary key)''')
        c.execute('''create table if not exists lists (list_id text pimary key, name text)''')
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
        # self._db.commit()
        c.close()

    def capture_sprint(self, sprint_id, snapshot_phase):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        cards = board.open_cards()
        c = self._db.cursor()
        # make sure cards exist
        for card in cards:
            self.write_card(card)
            # write them to state
            c.execute('''insert into sprint_state values (?, ?, ?, ?, ?)''',
                      (sprint_id.date(), card.list_id, card.id, snapshot_phase, 0))
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
            self.capture_sprint(self.last_sprint_start, snapshot_phase=2)
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e
        self.set_sprint_flag('finished', self.last_sprint_id)
        self._db.commit()

        # archive all cards in Done column
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        done_list = board.get_list(self.list_ids['Done'])
        done_cards = done_list.list_cards()
        for card in done_cards:
            if not card.closed:
                print "Closing Done ticket: %s" % card.name
                card.set_closed(True)


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
        
        ## capture tickets coming in from roadmap (so we can figure out which were added ad hoc after sprint start)

        self.set_sprint_flag('prepared', self.cur_sprint_id)
        self._db.commit()

    def start_sprint(self):
        self.ensure('prepared', self.last_sprint_id)
        self.ensure_not('started', self.last_sprint_id)
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=0
        ## run after prep and after any manual tickets have been added, to capture sprint start
        ## capture sprint board state to sqlite (start)
        self.capture_sprint(self.cur_sprint_start, snapshot_phase=1)

    def backup(self):
        # send to s3
        pass

    def report(self):
        # reports
        # outgoing
        ### num in each column
        ### num overdue
        ### avg age of open tickets
        ### avg length in sprint
        ### num fires (label)
        # incoming
        ### num incoming from sprint roadmaps
        ### total new (assuming some added manually from outside sprint roadmap)
        pass

if __name__ == "__main__":

    args = docopt(__doc__)
    # print args

    if args['<command>'] is None:
        args['<command>'] = 'show'

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
    else:
        print "unknown command: %s" % args['<command>']


