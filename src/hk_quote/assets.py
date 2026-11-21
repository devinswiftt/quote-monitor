"""Deployment guards against CSS files accidentally overwritten by scripts/HTML."""
import re


def validate_stylesheet(content):
    if re.search(r'^\s*(?:const|let|var|function|window\.)\b',content,re.M) or re.search(r'<(?:!doctype|html|script)\b',content,re.I):
        raise ValueError('样式文件包含 JavaScript 或 HTML')
    # Strip comments and strings before checking CSS structural delimiters.
    text=re.sub(r'/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '',content,flags=re.S)
    depth=0
    for char in text:
        if char=='{':depth+=1
        elif char=='}':
            depth-=1
            if depth<0:raise ValueError('CSS 花括号不匹配')
    if depth or '{' not in text:raise ValueError('CSS 规则缺失或不完整')
