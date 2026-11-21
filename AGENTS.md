# 前端变更验证

- 修改网页后必须运行 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q`，其中 `test_web_assets` 检查 CSS 被 JS/HTML 覆盖的问题。
- 使用 JavaScriptCore 执行适用的 `tests/test_web_disclosures.js`、`tests/test_chart_hover.js`、`tests/test_chart_lunch.js`。
- 发布前校验各资源内容与类型：CSS 需通过 `hk_quote.assets.validate_stylesheet`，不能只检查 HTTP 200、MIME 或文件字节一致。
- 多文件修改分别使用明确的路径与内容变量；禁止在循环/复用变量后追加一次不明内容的 write_text。先验证临时文件，再原子替换正式文件。
- 网页布局变化还需尽可能做浏览器视觉检查；没有做视觉检查时不要声称已验证实际页面外观。
