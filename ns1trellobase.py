from trello import TrelloClient, Member
import os
import sys


class NS1Base(object):

    # https://trello.com/b/1diHBDGp/
    SPRINT_BOARD_ID = '56b0bee08a91f6b079ba6ae9'

    def __init__(self):
        self.client = None
        self._me = None

    def check_api_key(self):
        if not os.getenv('TRELLO_API_KEY') or not os.getenv('TRELLO_API_SECRET'):
            raise Exception("You must define TRELLO_API_KEY and TRELLO_API_SECRET, from these: https://trello.com/app-key")

    def check_oauth(self):
        if not os.getenv('TRELLO_OAUTH_KEY') or not os.getenv('TRELLO_OAUTH_SECRET'):
            from trello import util
            util.create_oauth_token()
            sys.exit(0)

    def init_client(self):
        self.client = TrelloClient(api_key=os.getenv('TRELLO_API_KEY'),
                                   api_secret=os.getenv('TRELLO_API_SECRET'),
                                   token=os.getenv('TRELLO_OAUTH_KEY'),
                                   token_secret=os.getenv('TRELLO_OAUTH_SECRET'))

    @property
    def me(self):
        if self._me:
            return self._me
        self._me = Member(self.client, 'me')
        self._me.fetch()
        return self._me

    def boot(self):
        self.check_api_key()
        self.check_oauth()
        self.init_client()

