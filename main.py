import arrow
from argparse import ArgumentParser
from csv import DictReader
from json import loads, dumps
from os.path import isfile
from time import sleep

from onepassword import OnePassword
from everydollar_api import EveryDollarAPI, By, WebDriverWait, EC


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
  return {formatter['remapper'][f]: formatter['converter'].get(formatter['remapper'][f], lambda v: v)(record[f]) for f in formatter['remapper'].keys()}


def _more_options(client):
  """ supplements the client with clicking more functionality so we can leverage the notes or check # fields """
  more_button = client.driver.find_element(By.XPATH, "//*[@id='TransactionModal_moreOptions']")
  more_button.click()

def _enter_note(client, note):
  """ supplements the clien with the ability to add a note """
  note_field = client.driver.find_element(By.XPATH, "//*[@name='note']")
  note_field.send_keys(note)

if __name__ == '__main__':
  # Currently only accepts chase's transaction output but could easily be extended
  formats = {
    'chase': {
      'remapper': DummyDict({'Details': 'type', 'Posting Date': 'date', 'Amount': 'amount', 'Description': 'merchant', 'Type': 'note'}),
      'converter': DummyDict({'type': lambda v: 'expense' if v.upper() == 'DEBIT' else 'income', 'amount': float, 'date': lambda v: arrow.get(v, 'MM/DD/YYYY')}),
    },
  }

  parser = ArgumentParser()
  parser.add_argument('transactions_file', type=lambda x: open(x, 'r') if isfile(x) else parser.error(f'The file {x} does not exist!'))
  parser.add_argument('input_format', type=lambda x: x if x in formats else parser.error(f'You must select one of the following formats: {formats.keys()}'), default='chase')
  parser.add_argument('--op-vault', type=str, default='Private')
  parser.add_argument('--op-title', type=str, default='Ramseysolutions')

  args = parser.parse_args()
  formatter = formats[args.input_format]
  records_generator = get_records(args.transactions_file, formatter)
  client = login(args.op_title, args.op_vault)
  for record in records_generator:
    try:
      client._open_transaction_menu()
    except Exception:
      # Fade out animation was taking too long so basically added this in case the element wasn't clickable
      sleep(2)
      element_clickable = EC.element_to_be_clickable((By.XPATH, client.ADD_TRANSACTION_BTN_XPATH))
      WebDriverWait(client.driver, client.timeout).until(element_clickable)
      client._open_transaction_menu()

    # Sometimes we're too fast and we need to wait for the modal to load
    client._wait_for_load(By.XPATH, client.SELECTOR_TYPE_EXPENSE)
    client._transaction_type(record.get('type', 'expense'))
    client._enter_amount(record['amount'])
    client._enter_date(record['date'])
    client._enter_merchant(record.get('merchant'))
    # make sure the notes field is visible before writing to it
    _more_options(client)
    _enter_note(client, record.get('note'))
    client._submit_transaction()
