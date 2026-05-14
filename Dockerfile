FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
ENV CATWEB_MCP_TRANSPORT=sse \
    CATWEB_MCP_HOST=0.0.0.0 \
    CATWEB_MCP_PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/sse')" 2>/dev/null || exit 1
CMD ["catweb-mcp"]
