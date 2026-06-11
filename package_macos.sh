#!/bin/zsh
set -euo pipefail

ROOT_DIR="${0:A:h}"
APP_NAME="产品信息收集"
VERSION="$(date +%Y%m%d-%H%M%S)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
STAGE_DIR="$BUILD_DIR/$APP_NAME"
ZIP_PATH="$DIST_DIR/${APP_NAME}-mac-${VERSION}.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$STAGE_DIR" "$DIST_DIR"

cp "$ROOT_DIR/product_info_agent.py" "$STAGE_DIR/"
cp "$ROOT_DIR/product_info_agent_web.py" "$STAGE_DIR/"
cp "$ROOT_DIR/product_info_agent.md" "$STAGE_DIR/"
cp "$ROOT_DIR/README.md" "$STAGE_DIR/"
cp "$ROOT_DIR/start_product_info_agent.command" "$STAGE_DIR/"
chmod +x "$STAGE_DIR/start_product_info_agent.command"

mkdir -p "$STAGE_DIR/agent_config" "$STAGE_DIR/samples" "$STAGE_DIR/product"
cp "$ROOT_DIR/agent_config/agent_settings.json" "$STAGE_DIR/agent_config/"
cp "$ROOT_DIR/agent_config/README.md" "$STAGE_DIR/agent_config/"
cp "$ROOT_DIR/samples/product_basic_info.txt" "$STAGE_DIR/samples/"

cat > "$STAGE_DIR/安装说明.txt" <<'EOF'
产品信息收集 - macOS 安装说明

1. 解压 zip。
2. 双击 start_product_info_agent.command。
3. 浏览器会打开 http://127.0.0.1:8791。
4. 产品 Markdown 会保存在解压目录下的 product 文件夹。

如果 macOS 提示无法打开：
- 右键 start_product_info_agent.command，选择“打开”。
- 或在终端进入该目录后执行：
  chmod +x start_product_info_agent.command
  ./start_product_info_agent.command

本程序只使用 Python 标准库，不调用外部 API。
EOF

(
  cd "$BUILD_DIR"
  /usr/bin/zip -qry "$ZIP_PATH" "$APP_NAME"
)

echo "$ZIP_PATH"
