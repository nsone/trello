#!/usr/bin/env python
"""
usage: tix.py [<command>] [<args>...]

Commands:

    list    List currently assigned tickets

"""

from docopt import docopt
from trello import Board
from ns1trellobase import NS1Base


class Tix(NS1Base):

    def list_tix(self):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        cards = board.open_cards()
        lists = board.open_lists()
        list_names = {l.id: l.name for l in lists}
        for c in cards:
            c.fetch(True)
            if self.me.id in c.member_ids:
                feature_id = c.shortUrl[-8:]
                print "%s | %s: %s | %s | %s" % (feature_id, c.name, c.desc[0:30],
                                                 list_names[c.list_id], c.shortUrl)

if __name__ == "__main__":

    args = docopt(__doc__)

    # print args
    if args['<command>'] is None:
        args['<command>'] = 'list'

    t = Tix()
    t.boot()

    if args['<command>'] == 'list':
        t.list_tix()




