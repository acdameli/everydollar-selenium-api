import arrow
from argparse import ArgumentParser
from csv import DictReader
from collections import defaultdict
from json import loads, dumps
from os.path import isfile
from time import sleep

from onepassword import OnePassword
from everydollar_api import EveryDollarAPI


class DummyDict(dict):
    """ Returns the key if the key is not found in the dictionary. The intent being if you provide a file that is in a valid format for EveryDollar already this maps each field to itself """
    def __missing__(self, key):
        return key


def login(docname, vault_name='Private'):
    """ Look up creds in 1pass in the indicated value for the indicated document name and return a logged in EveryDollar client """
    op = OnePassword()

    creds = op.get_item(op.get_uuid(docname, vault_name), fields=['username', 'password'])
    client = EveryDollarAPI(False)
    client.login(creds['username'], creds['password'])
    return client


def get_records(file_pointer, formatter=None):
    """ Efficiently load a normalized version of each row in the provided file pointer """
    for r in DictReader(file_pointer):
        yield reformat_record(r, formatter)


def reformat_record(record, formatter):
    """ reformat a single record by renaming the keys and performing any indicated conversions. The identity function is the fallback if no converter found. """
    remapper = formatter['remapper']
    converter = formatter['converter']
    return {
        # converter not found, use identity function, pass value to converter
        remapper[f]: converter.get(remapper[f], lambda v: v)(record[f])
        for f in remapper.keys()
    }

if __name__ == '__main__':
    # Currently only accepts chase's transaction output but could easily be extended
    formats = {
        'chase': {
            'remapper': DummyDict({
                'Details': 'type',
                'Posting Date': 'date',
                'Amount': 'amount',
                'Description': 'merchant',
                'Type': 'note',
            }),
            # return the value unmodified
            'converter': defaultdict(lambda x: x, {
                'type': lambda v: {'DEBIT': 'expense'}.get(v.upper(), 'income'),
                'amount': float,
                'date': lambda v: arrow.get(v, 'MM/DD/YYYY')
            }),
        },
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
    formatter = formats[args.input_format]

    records_generator = get_records(args.transactions_file, formatter)
    client = login(args.op_title, args.op_vault)

    for record in records_generator:
        client.add_transaction(record['date'], record['merchant'], record['amount'], record['type'], record['note'])
