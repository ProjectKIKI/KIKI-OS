FROM localhost/kiki-buildd:native-20261023
USER 0:0
COPY ki2ci_auth.py /app/ki2ci_auth.py
COPY ki2users.py ki2users_views.py /app/
COPY ki2ci_theme.py ki2ci_theme.css ki2ci_theme.js /app/
COPY ki2ci_ko.py ki2ci_catalog_ko.json ki2ci_ui.js /app/
EXPOSE 8092/tcp
ENTRYPOINT ["/usr/bin/python3", "-I", "-B", "/app/ki2ci_auth.py"]
