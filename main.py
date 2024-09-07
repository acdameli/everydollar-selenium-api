import arrow
from abc import abstractmethod
from functools import cached_property
from argparse import ArgumentParser
from csv import DictReader
from collections import defaultdict
from json import loads, dumps
from os.path import isfile, getsize
from time import sleep

from onepassword import OnePassword
from everydollar_api import EveryDollarAPI


class DummyDict(dict):
    """ Returns the key if the key is not found in the dictionary. The intent being if you provide a file that is in a valid format for EveryDollar already this maps each field to itself """
    def __missing__(self, key):
        return key


_ = lambda x: x


def login(docname, vault_name='Private'):
    """ Look up creds in 1pass in the indicated value for the indicated document name and return a logged in EveryDollar client """
    op = OnePassword()

    creds = op.get_item(op.get_uuid(docname, vault_name), fields=['username', 'password'])
    client = EveryDollarAPI(False)
    client.login(creds['username'], creds['password'])
    return client


class ExtractTransform:
    def __init__(self, fp, config: dict | None = None):
        self.config = config
        self.fp = fp
        self.file_size = getsize(self.fp.name)

    @property
    def progress(self):
        return self.fp.tell()/self.file_size

    @property
    def records(self):
        """ Efficiently load a normalized version of each row in the provided file pointer """
        for r in DictReader(self.fp):
            yield self.reformat_record(r)

        self.fp.seek(0)

    @abstractmethod
    def reformat_record(self, record):
        pass


class Chase(ExtractTransform):
    def reformat_record(self, record):
        """ reformat a single record by renaming the keys and performing any indicated conversions. """
        return {
            # converter not found, use identity function, pass value to converter
            self.reformat_key(f): self.convert_data(f, record)
            for f in ['Details', 'Posting Date', 'Amount', 'Description', 'Type']
        }

    def reformat_key(self, key: str) -> str:
        return {
            'Details': 'type',
            'Posting Date': 'date',
            'Amount': 'amount',
            'Description': 'merchant',
            'Type': 'note',
        }.get(key, key)

    def convert_data(self, key: str, record: dict[str, str]) -> str | float | None:
        return {
            'Details': lambda v: {'DEBIT': 'expense'}.get(v.upper(), 'income'),
            'Amount': float,
            'Posting Date': lambda v: arrow.get(v, 'MM/DD/YYYY')
        }.get(key, _)(record[key])


if __name__ == '__main__':
    # Currently only accepts chase's transaction output but could easily be extended
    formats = {
        'chase': Chase,
    }

    parser = ArgumentParser()
    def file_or_error(arg):
        if not isfile(arg):
            parser.error(f'The file {arg} does not exist!')

        return open(arg, 'r')

    parser.add_argument(
        'transactions_file',
        type=file_or_error
    )
    parser.add_argument(
        'input_format',
        type=str,
        choices=list(formats.keys()),
        default='chase'
    )
    parser.add_argument('--op-vault', type=str, default='Private')
    parser.add_argument('--op-title', type=str, default='Ramseysolutions')

    args = parser.parse_args()

    client = login(args.op_title, args.op_vault)

    for record in formats[args.input_format](args.transactions_file).records:
        client.add_transaction(record['date'], record['merchant'], record['amount'], record['type'], record['note'])
