# RNFE v16 Claude Guide

Use the shared Obsidian Mind vault at `ai/obsidian-mind/` for persistent project memory.

Read `AGENTS.md` first, then use `ai/obsidian-mind/CLAUDE.md` as the full vault operating manual. Keep RNFE project facts in `ai/obsidian-mind/brain/` and active implementation notes in `ai/obsidian-mind/work/active/`.

Respect the RNFE guardrails:

- `canon/normative/` is normative.
- `docs/analysis/00_INDEX.md` reflects the audited state of the code.
- `docs/history/` is historical and may be stale.
- `archive/` is quarantined legacy.
- The Obsidian vault is agent/developer memory, not RNFE runtime memory.

## Cartografía del proyecto

Este proyecto mantiene un mapa vivo del código en una base local (SQLite, sin embeddings).

**Dos capas, con orígenes distintos.** La capa estructural (archivos, símbolos, imports, referencias, líneas) se genera con un parser automático y nunca se escribe a mano. La capa de intención la escribe Claude: para qué existe cada nodo, qué decisión lo originó, y de qué depende conceptualmente aunque no haya import que lo delate.

**Actualización.** Cuando se edita un archivo, ese nodo y sus vecinos directos quedan marcados como pendientes de intención. Al cerrar el turno, Claude resuelve la cola de pendientes antes de devolver el control. No se espera a que el usuario lo pida.

**Uso del mapa.** Antes de leer código, Claude consulta el mapa y abre solo los nodos relevantes a la tarea. Cada nodo registra su costo de lectura: tamaño y qué otros nodos hay que abrir sí o sí para entenderlo.

**Registro negativo.** Si un archivo se abrió y resultó irrelevante para la tarea, queda anotado como tal. No se vuelve a abrir para tareas del mismo tipo.

**Límite.** El mapa se consulta cuando la tarea toca territorio desconocido o amplio. Para cambios acotados en archivos ya conocidos, se va directo al código. Consultar el mapa en toda tarea gasta más de lo que ahorra.
