FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Shanghai
COPY requirements-nas.txt /app/requirements-nas.txt
COPY offline-deps/wheels/ /tmp/wheels/
RUN python -m pip install --no-index --no-cache-dir --find-links=/tmp/wheels -r requirements-nas.txt \
    && rm -rf /tmp/wheels
RUN python -c "from importlib.resources import files; from pathlib import Path; p=Path('/usr/share/zoneinfo/Asia'); p.mkdir(parents=True, exist_ok=True); (p/'Shanghai').write_bytes(files('tzdata.zoneinfo').joinpath('Asia/Shanghai').read_bytes())" \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
COPY src/mom_index/ /app/src/mom_index/
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["web"]
