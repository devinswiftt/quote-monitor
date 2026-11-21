"""Chinese security names verified from OpenD market snapshots."""
NAMES = {'HK.02065': '一微科技', 'HK.02206': '新荷花', 'HK.09621': '远信储能'}


def stock_label(code, name=None):
    return f'{name or NAMES.get(code, code)}（{code}）'
