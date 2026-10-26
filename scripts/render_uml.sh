#!/usr/bin/env bash
# Render every PlantUML diagram (docs/uml/*.puml) to PNG in docs/report/figures/, where the
# report build (scripts/build_report.py) picks them up. Needs Java and plantuml.jar:
#   PLANTUML_JAR=/path/to/plantuml.jar ./scripts/render_uml.sh
# (plantuml.jar from https://plantuml.com/download or Maven Central net.sourceforge.plantuml).
# The smetana layout avoids needing Graphviz for class, use case and component diagrams.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PLANTUML_JAR:?set PLANTUML_JAR to the path of plantuml.jar}"
mkdir -p docs/report/figures
java -Djava.awt.headless=true -DPLANTUML_LIMIT_SIZE=16384 -jar "$PLANTUML_JAR" \
  -tpng -Playout=smetana -failfast2 -o "$PWD/docs/report/figures" docs/uml/*.puml
echo "rendered $(ls docs/report/figures/*.png | wc -l | tr -d ' ') diagrams into docs/report/figures/"
