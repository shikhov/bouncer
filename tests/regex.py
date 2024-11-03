from pymongo import MongoClient
import sys

sys.path.append('app\\src')
sys.path.append('config')
from regex_checker import RegexChecker
from test_data.regex_test_data import test_data
from config_prod import CONNSTRING, DBNAME

C_HEADER = '\033[95m'
C_BLUE = '\033[94m'
C_CYAN = '\033[96m'
C_GREEN = '\033[92m'
C_WARNING = '\033[93m'
C_FAIL = '\033[91m'
C_ENDC = '\033[0m'
C_BOLD = '\033[1m'
C_UNDERLINE = '\033[4m'

def do_test():
    line = '='*10
    print(f'\n{line}[ {C_WARNING}{DBNAME}{C_ENDC} ]{line}\n')

    db = MongoClient(CONNSTRING).get_database(DBNAME)
    settings = db.settings.find_one({'_id': 'settings'})
    regexChecker = RegexChecker()
    regexChecker.load_list(settings['REGEX_LIST'], {'regex': {}})

    pass_count = 0
    fail_count = 0

    for text, expectation in test_data.items():
        result = regexChecker.check(text)
        if result == expectation:
            pass_count += 1
            regex = f'{C_CYAN} {regexChecker.matched_regex}{C_ENDC}' if regexChecker.matched_regex else ''
            print(f'{C_GREEN}PASS:{C_ENDC}{regex} {text}')
        else:
            fail_count += 1
            print(f'{C_FAIL}FAIL:{C_ENDC} {text}')

    failed = f'FAILED: {C_FAIL}{fail_count}{C_ENDC}' if fail_count else f'FAILED: {C_GREEN}{fail_count}{C_ENDC}'
    passed = f'PASSED: {C_GREEN}{pass_count}{C_ENDC}'
    print(f'{passed}\n{failed}')


do_test()
