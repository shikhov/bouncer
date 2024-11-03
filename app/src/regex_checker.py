import re


class RegexChecker:
    def __init__(self) -> None:
        self.rlist = {}
        self.matched_regex = None

    def load_list(self, regex_list, stat):
        SUBS = {
            'а': 'a',
            'к': 'k',
            'и': 'u',
            'р': 'p',
            'о': 'o0',
            'е': 'ёe',
            'т': 't',
            'с': 'c',
            'н': 'h',
            'в': 'b',
            'з': '3',
            'у': 'y',
            'х': 'x'
        }
        tmp = {}

        for regex in regex_list:
            out_regex = ''
            for char in regex:
                if char in SUBS:
                    out_regex += '[' + char + SUBS[char] + ']'
                else:
                    out_regex += char
            tmp[regex] = {
                'regex': out_regex,
                'count': stat['regex'].get(regex, 0)
            }
            if regex.startswith(r'[\u'):
                tmp[regex]['flags'] = re.IGNORECASE + re.ASCII

        self.rlist = dict(sorted(tmp.items(), key=lambda item: item[1]['count'], reverse=True))

    def check(self, text):
        if not text: return False
        for key, value in self.rlist.items():
            regex = value['regex']
            flags = value.get('flags', re.IGNORECASE + re.UNICODE)
            if re.search(regex, text, flags):
                self.matched_regex = key
                return True

        return False

    def updateStat(self, stat):
        if not self.matched_regex:
            return
        self.rlist[self.matched_regex]['count'] += 1
        self.rlist = dict(sorted(self.rlist.items(), key=lambda item: item[1]['count'], reverse=True))
        stat['regex'][self.matched_regex] = stat['regex'].get(self.matched_regex, 0) + 1
        self.matched_regex = None