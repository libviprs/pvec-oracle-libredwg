# pvec-oracle-libredwg: open DWG to STEP converter built on GNU LibreDWG (GPL-3.0-or-later).
#
#   docker build --platform linux/amd64 -t pvec-oracle-libredwg .
#   docker build --platform linux/arm64 -t pvec-oracle-libredwg .
#
# Inputs are pinned: the base image by digest (the multi-arch index, so arm64 and x86_64 resolve the
# same release) and the LibreDWG release tarball by sha256. The build stops if the tarball does not
# match. apt packages in the build stage are not version-pinned, but nothing from them ends up in the
# output except the compiled binaries (see docs/qualification.md, "What is not pinned").
ARG BASE=debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

FROM ${BASE} AS build
ARG LIBREDWG_VERSION=0.14
ARG LIBREDWG_SHA256=62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275
ARG LIBREDWG_URL=https://ftp.gnu.org/gnu/libredwg/libredwg-${LIBREDWG_VERSION}.tar.xz
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl pkg-config xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL -o libredwg.tar.xz "${LIBREDWG_URL}" \
    && echo "${LIBREDWG_SHA256}  libredwg.tar.xz" | sha256sum -c - \
    && mkdir libredwg && tar -xJf libredwg.tar.xz -C libredwg --strip-components=1
# Two builds of the same release, both static, no bindings, no docs. -ffp-contract=off keeps the
# floating point results the same on arm64 and x86_64.
#   /opt/stock   unmodified LibreDWG: dwgread
#   /opt/exact   the same source plus patches/0001 (doubles in JSON with 17 significant digits)
# The stock JSON writer prints doubles with "%.14f", which cannot carry a binary64 value, so the
# converter reads the patched one. The stock binary is kept so the loss can be shown.
COPY patches /src/patches
RUN cp -a libredwg libredwg-exact \
    && cd libredwg-exact && patch -p1 --dry-run < /src/patches/0001-json-doubles-17-significant-digits.patch \
    && patch -p1 < /src/patches/0001-json-doubles-17-significant-digits.patch
RUN cd /src/libredwg && CFLAGS="-O2 -ffp-contract=off" ./configure --prefix=/opt/stock \
        --disable-shared --enable-static --disable-bindings --disable-python \
        --disable-docs --disable-werror --disable-trace \
    && make -j"$(nproc)" && make install && /opt/stock/bin/dwgread --version
RUN cd /src/libredwg-exact && CFLAGS="-O2 -ffp-contract=off" ./configure --prefix=/opt/exact \
        --disable-shared --enable-static --disable-bindings --disable-python \
        --disable-docs --disable-werror --disable-trace \
    && make -j"$(nproc)" && make install && /opt/exact/bin/dwgread --version

FROM ${BASE} AS runtime
ARG LIBREDWG_VERSION=0.14
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/stock/bin/dwgread /usr/local/bin/dwgread
COPY --from=build /opt/exact/bin/dwgread /usr/local/bin/dwgread-exact
# dwgwrite is only here so the tests can write a DWG that holds chosen values (tests/test_json_exponents.py)
COPY --from=build /opt/exact/bin/dwgwrite /usr/local/bin/dwgwrite-exact
# The corresponding source of the GPL binaries travels with them, with the patch.
COPY patches /usr/share/doc/pvec-oracle-libredwg/source/patches
COPY --from=build /src/libredwg.tar.xz /usr/share/doc/pvec-oracle-libredwg/source/libredwg-${LIBREDWG_VERSION}.tar.xz
COPY --from=build /src/libredwg/COPYING /usr/share/doc/pvec-oracle-libredwg/COPYING.libredwg
COPY LICENSE /usr/share/doc/pvec-oracle-libredwg/COPYING
COPY dwg2step.py dwgdump.py /usr/local/bin/
COPY libredwg_json.py /usr/local/lib/pvec-oracle/libredwg_json.py
ENV PYTHONPATH=/usr/local/lib/pvec-oracle PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
    LIBREDWG_VERSION=${LIBREDWG_VERSION}
RUN chmod 0755 /usr/local/bin/dwg2step.py /usr/local/bin/dwgdump.py \
    && ln -s dwg2step.py /usr/local/bin/dwg2step && ln -s dwgdump.py /usr/local/bin/dwgdump
WORKDIR /work
ENTRYPOINT []
