#!/usr/bin/env python3
"""Provisión del workload GPU: llama.cpp-CUDA + GGUFs (razonador + embeddings).

Este es el ÚNICO paso que necesita red/descargas. Todo el núcleo (router real,
sensado GPU, razonador admitido, seam de embeddings) funciona sin él; sin
artefactos, el razonador devuelve skip y los embeddings caen a Jaccard.

Uso (con el usuario, confirmando tamaños):
  # 1) Diagnóstico (sin red): qué GPU hay y qué falta.
  python scripts/provision_llama_gpu.py --check

  # 2) Descarga (necesita red + consentimiento; ~4.5GB el GGUF del 7B).
  python scripts/provision_llama_gpu.py --download --models-root ~/rnfe_models

  # 3) Escribir el .env nativo con las rutas resueltas.
  python scripts/provision_llama_gpu.py --write-env .env.external_reasoner.local --models-root ~/rnfe_models

  # 4) Smoke en la GPU (una llamada real; observá el salto de VRAM en nvidia-smi).
  python scripts/provision_llama_gpu.py --smoke --models-root ~/rnfe_models

Diseño: por defecto NO descarga nada. Requiere --download explícito para tocar la red.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# GGUF del razonador (coincide con .env.external_reasoner.example).
REASONER_REPO = "lmstudio-community/OpenThinker3-7B-GGUF"
REASONER_FILE = "OpenThinker3-7B-Q4_K_M.gguf"
REASONER_SHA256 = "0b7344e4bf1c68fc40c4a10b14b9bd51f367423b8453d83544ea5bdbe08e7e5e"

# GGUF de embeddings (pequeño, ~80MB).
EMBED_REPO = "nomic-ai/nomic-embed-text-v1.5-GGUF"
EMBED_FILE = "nomic-embed-text-v1.5.Q4_K_M.gguf"
# SHA-256 del embed. VACÍO a propósito: no se conoce el hash real sin una
# descarga verificada previa y NO se inventa un valor. Semántica en
# `_verify_or_fail`: si está seteado -> fail-closed (igual que el razonador);
# si está vacío -> advertencia UNVERIFIED explícita (no falla).
# Para pinnearlo: bajá una vez, verificá el origen del artefacto, y copiá el
# `sha256=<...>` que imprime la advertencia UNVERIFIED en esta constante.
EMBED_SHA256 = ""

# llama.cpp NO publica binario CUDA para Linux; el camino que usa la GPU sin toolkit
# es el backend VULKAN (el RTX 2070 es un dispositivo Vulkan vía el driver NVIDIA).
LLAMA_TAG = "b9874"
LLAMA_VULKAN_ASSET = f"llama-{LLAMA_TAG}-bin-ubuntu-vulkan-x64.tar.gz"
LLAMA_VULKAN_URL = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{LLAMA_VULKAN_ASSET}"
)
LLAMA_RELEASE_HINT = (
    f"Bajá {LLAMA_VULKAN_URL} y descomprimí en "
    "<models-root>/tools/llama.cpp/build-vulkan (backend Vulkan, offload a la GPU con -ngl)."
)

# SHA-256 del BINARIO llama.cpp Vulkan. VACÍO a propósito, con la MISMA semántica
# que EMBED_SHA256: no tenemos el binario verificado, así que NO se inventa un valor.
# El runtime EJECUTA este binario como código nativo -> su integridad importa tanto
# como la del GGUF (dato). En `_verify_or_fail`: si está seteado -> fail-closed (borra
# el tar + aborta la extracción); si está vacío -> advertencia UNVERIFIED explícita.
# Para pinnearlo (deuda ya ruteada a backlog B56): bajá el asset del release `b9874`
# (LLAMA_VULKAN_ASSET), verificá su origen, y copiá acá el `sha256=<...>` que imprime
# la advertencia UNVERIFIED.
LLAMA_VULKAN_SHA256 = ""


def _gpu_info() -> str | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return (out.stdout or "").strip() or None


def _find_llama_cli(models_root: Path) -> Path | None:
    env = os.environ.get("RNFE_LLAMA_CLI_CUDA", "").strip()
    if env and Path(env).exists():
        return Path(env)
    base = models_root / "tools" / "llama.cpp"
    # Busca el llama-cli del build Vulkan (o cualquier subdir del release).
    for pattern in ("build-vulkan/**/llama-cli", "build-cuda/**/llama-cli", "**/llama-cli"):
        for candidate in base.glob(pattern):
            if candidate.is_file():
                return candidate
    found = shutil.which("llama-cli")
    return Path(found) if found else None


def _is_within(base: Path, target: Path) -> bool:
    """True si `target` (ya resuelto) queda dentro del árbol de `base` (resuelto)."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _safe_extractall(tf, dest_dir: Path) -> None:
    """Extracción endurecida de un tar: bloquea tar-slip / Zip-Slip.

    Rechaza, ANTES de escribir nada:
      - miembros cuya ruta resuelta cae fuera de `dest_dir` (``../`` o rutas absolutas),
      - symlinks/hardlinks cuyo destino apunta fuera de `dest_dir`.

    En Python 3.12+ aplica además el filtro 'data' de la stdlib como defensa en
    profundidad; el validador manual garantiza el comportamiento seguro también
    en <3.12 (donde `extractall(..., filter=...)` no existe).
    """
    base = dest_dir.resolve()
    for member in tf.getmembers():
        target = (base / member.name).resolve()
        if not _is_within(base, target):
            raise ValueError(
                f"tar inseguro: miembro fuera del destino: {member.name!r}"
            )
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            if not _is_within(base, link_target):
                raise ValueError(
                    f"tar inseguro: link fuera del destino: "
                    f"{member.name!r} -> {member.linkname!r}"
                )
    try:
        tf.extractall(dest_dir, filter="data")  # type: ignore[call-arg]
    except TypeError:
        # Python <3.12: sin kwarg 'filter'. Ya validamos todos los miembros arriba.
        tf.extractall(dest_dir)  # noqa: S202


def _download_llama_vulkan(models_root: Path) -> Path | None:
    import tarfile
    import urllib.request

    dest_dir = models_root / "tools" / "llama.cpp" / "build-vulkan"
    dest_dir.mkdir(parents=True, exist_ok=True)
    tar_path = dest_dir / LLAMA_VULKAN_ASSET
    print(f"  bajando {LLAMA_VULKAN_ASSET} ...")
    try:
        urllib.request.urlretrieve(LLAMA_VULKAN_URL, tar_path)
        # Integridad del BINARIO antes de extraer/ejecutar: mismo helper fail-closed
        # que el GGUF (dato). Con LLAMA_VULKAN_SHA256 vacío es UNVERIFIED (advierte y
        # sigue); una vez pinneado, un mismatch borra el tar y aborta la extracción.
        _verify_or_fail(tar_path, LLAMA_VULKAN_SHA256, "binario llama.cpp Vulkan")
        with tarfile.open(tar_path, "r:gz") as tf:
            _safe_extractall(tf, dest_dir)
    except IntegrityError as exc:
        # Distinguir un fallo de INTEGRIDAD (fail-closed) de un error de red/tar, para
        # no rotular un mismatch de hash como "error bajando".
        print(f"  ERROR de integridad del binario: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR bajando llama.cpp: {type(exc).__name__}: {exc}")
        return None
    return _find_llama_cli(models_root)


def _paths(models_root: Path) -> dict[str, Path]:
    return {
        "reasoner_gguf": models_root / "gguf" / "OpenThinker3-7B" / REASONER_FILE,
        "embed_gguf": models_root / "gguf" / "embeddings" / EMBED_FILE,
    }


def cmd_check(models_root: Path) -> int:
    gpu = _gpu_info()
    print("== Diagnóstico de provisión GPU ==")
    print(f"GPU: {gpu or 'NO detectada (nvidia-smi ausente o sin GPU)'}")
    cli = _find_llama_cli(models_root)
    print(f"llama.cpp CUDA cli: {cli or 'FALTA -> ' + LLAMA_RELEASE_HINT}")
    paths = _paths(models_root)
    reasoner_status = (
        "OK " + str(paths["reasoner_gguf"])
        if paths["reasoner_gguf"].exists()
        else "FALTA " + str(paths["reasoner_gguf"])
    )
    print(f"reasoner_gguf: {reasoner_status}")
    embedding_mode = os.environ.get("RNFE_MEMORY_EMBEDDINGS", "").strip().lower()
    embedding_required = embedding_mode in {"llama", "llama_cpp", "gpu"}
    embed_status = (
        "OK " + str(paths["embed_gguf"])
        if paths["embed_gguf"].exists()
        else "FALTA " + str(paths["embed_gguf"])
    )
    if not embedding_required:
        embed_status += " (opcional; RNFE_MEMORY_EMBEDDINGS no está en llama)"
    print(f"embed_gguf: {embed_status}")
    missing = []
    if not paths["reasoner_gguf"].exists():
        missing.append("reasoner_gguf")
    if embedding_required and not paths["embed_gguf"].exists():
        missing.append("embed_gguf")
    if not cli:
        missing.append("llama_cli")
    if missing:
        print(f"\nFaltan: {', '.join(missing)}")
        print("Corré con --download para bajar los artefactos requeridos (necesita red).")
        return 1
    print("\nTodo presente. Usá --write-env para generar el .env y --smoke para probar en GPU.")
    return 0


def _hf_download(repo: str, filename: str, dest: Path) -> Path:
    from huggingface_hub import hf_hub_download  # type: ignore

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  bajando {repo}/{filename} ...")
    local = hf_hub_download(repo_id=repo, filename=filename)
    shutil.copy(local, dest)
    return dest


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class IntegrityError(RuntimeError):
    """Fallo de integridad de un artefacto descargado (fail-closed)."""


def _verify_or_fail(path: Path, expected_sha: str, label: str) -> None:
    """Verifica el SHA-256 de `path` contra `expected_sha`. Fail-closed.

    - `expected_sha` seteado y NO coincide -> borra el artefacto corrupto del
      disco y lanza ``IntegrityError`` (un mismatch de integridad es un fallo de
      seguridad, no un warning).
    - `expected_sha` seteado y coincide     -> OK.
    - `expected_sha` vacío ("")             -> advertencia UNVERIFIED explícita y
      NO falla. Espeja el guard ``if REASONER_SHA256 and ...`` original pero es
      estrictamente mejor que el no-check silencioso: avisa e imprime el hash
      observado para poder pinnearlo.
    """
    expected = (expected_sha or "").strip().lower()
    if not expected:
        print(
            f"  UNVERIFIED [{label}] — sin hash pinneado, no se puede verificar "
            "integridad; pinnear tras la primera descarga verificada "
            f"(sha256={_sha256(path)})."
        )
        return
    digest = _sha256(path).lower()
    if digest != expected:
        try:
            path.unlink()
        except OSError:
            pass
        raise IntegrityError(
            f"[{label}] SHA256 no coincide: {digest} != {expected}. "
            "Artefacto corrupto borrado del disco (fail-closed)."
        )
    print(f"  OK [{label}] SHA256 verificado.")


def cmd_download(models_root: Path, *, embeddings: bool) -> int:
    print("== Descarga de artefactos (red) ==")
    paths = _paths(models_root)
    try:
        if not paths["reasoner_gguf"].exists():
            _hf_download(REASONER_REPO, REASONER_FILE, paths["reasoner_gguf"])
        # Verificar SIEMPRE, FUERA del guard exists(): un artefacto preexistente
        # (parcial por el copy no atómico, o plantado por un atacante local) NO debe
        # saltear la verificación e imprimir "Descarga OK". exists() no es prueba de
        # integridad; solo un hash OK habilita el return 0.
        _verify_or_fail(paths["reasoner_gguf"], REASONER_SHA256, "reasoner_gguf")
        if embeddings:
            if not paths["embed_gguf"].exists():
                _hf_download(EMBED_REPO, EMBED_FILE, paths["embed_gguf"])
            _verify_or_fail(paths["embed_gguf"], EMBED_SHA256, "embed_gguf")
    except IntegrityError as exc:
        print(f"  ERROR de integridad: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - reporte claro al usuario
        print(f"  ERROR de descarga: {type(exc).__name__}: {exc}")
        return 1
    cli = _find_llama_cli(models_root)
    binary_verified_path = False
    if cli is None:
        print("  binario llama.cpp ausente -> bajando build Vulkan ...")
        cli = _download_llama_vulkan(models_root)  # este camino pasa por _verify_or_fail
        binary_verified_path = cli is not None
    if cli is None:
        print(f"\nNo se pudo obtener el binario. {LLAMA_RELEASE_HINT}")
        return 1
    if not binary_verified_path:
        # Binario PREEXISTENTE/out-of-band: NO pasó por la descarga verificada. El
        # runtime lo EJECUTA como código nativo; su integridad no está garantizada.
        # Mismo criterio de honestidad que el GGUF/embed: advertir explícito en vez de
        # dejar pasar en silencio (es el mismo exists()-skip que cerramos para el dato,
        # aplicado ahora al binario). Un pin a nivel binario (distinto del tar) queda en
        # backlog B56.
        print(
            f"  UNVERIFIED [binario llama.cpp] — usando binario preexistente sin "
            f"verificar integridad: {cli}. Re-provisioná con --download sobre un "
            "models-root limpio (o pinneá el hash) para garantizar el código que "
            "ejecuta el runtime."
        )
    print(f"Descarga OK. llama-cli: {cli}")
    return 0


def cmd_write_env(
    models_root: Path,
    out: Path,
    *,
    vk_device: str = "1",
    enable_external_reasoner: bool = False,
) -> int:
    import re

    # vk_device se interpola crudo en el .env; restringirlo a índice(s) numéricos evita
    # que un valor con salto de línea inyecte líneas `export` en el archivo generado.
    if not re.fullmatch(r"[0-9]+(,[0-9]+)*", vk_device):
        print(
            f"  ERROR: --vk-device inválido: {vk_device!r} (esperado índice(s) numéricos, "
            "p.ej. '1' o '0,1'). Se rechaza para evitar inyección en el .env."
        )
        return 2
    cli = _find_llama_cli(models_root)
    paths = _paths(models_root)
    cli_path = str(cli or models_root / "tools/llama.cpp/build-vulkan/llama-cli")
    if cli is not None:
        print(
            f"  nota [integridad]: se escribe {cli} al .env sin verificación aquí; "
            "la integridad del binario se chequea en --download (o pinneá el hash)."
        )
    # Gobernanza del razonador externo: TRES claves que, juntas, lo arman. La MAESTRA
    # es RNFE_EXTERNAL_REASONER_RUNTIME — la leen el camino vivo
    # (runtime/world/scenario_runner.py:44) y la admisión del scheduler
    # (runtime/reasoning/scheduler_meta/policy.py:27), y de ella scripts/life_kernel.py:75
    # deriva el default de allow_external. Las otras dos (ALLOW_EXTERNAL + MAX_COMPUTE_TIER)
    # fijan el permiso y el techo tier_3. OPT-IN por defecto: auto-setear CUALQUIERA de
    # ellas en un .env que el operador hace `source` derrota el gate por diseño (queda
    # siempre-on) y arma la ejecución de un binario no verificado. Con
    # --enable-external-reasoner se emiten activas; sin el flag, las TRES salen comentadas.
    if enable_external_reasoner:
        governance = [
            "export RNFE_EXTERNAL_REASONER_RUNTIME=1",
            "export RNFE_ALLOW_EXTERNAL_REASONER=1",
            "export RNFE_MAX_COMPUTE_TIER=tier_3_external",
        ]
    else:
        governance = [
            "# descomentar las TRES para habilitar el razonador externo tier_3 (requiere binario y GGUF verificados)",
            "# export RNFE_EXTERNAL_REASONER_RUNTIME=1",
            "# export RNFE_ALLOW_EXTERNAL_REASONER=1",
            "# export RNFE_MAX_COMPUTE_TIER=tier_3_external",
        ]
    lines = [
        f'export RNFE_MODELS_ROOT="{models_root}"',
        f'export RNFE_REASONING_GGUF="{paths["reasoner_gguf"]}"',
        f"export RNFE_EXPECTED_GGUF_SHA256={REASONER_SHA256}",
        # DEUDA DE NOMENCLATURA (intencional, NO renombrar): el binario es Vulkan,
        # pero el config del organismo lee estas claves con nombre "CUDA"
        # (RNFE_LLAMA_CLI_CUDA / RNFE_EXTERNAL_REASONER_BACKEND=cuda) como el único
        # camino con offload -ngl>0. Renombrarlas ROMPE el contrato config<->script.
        # La deuda vive en el config, no acá; ver informe (candidata a backlog).
        "# backend real: vulkan (nombre CUDA por contrato del config)",
        f'export RNFE_LLAMA_CLI_CUDA="{cli_path}"',
        f'export RNFE_LLAMA_CLI_CPU="{cli_path}"',
        "export RNFE_EXTERNAL_REASONER_BACKEND=cuda",
        "export RNFE_EXTERNAL_REASONER_NGL=99",
        # Aísla el RTX 2070 del iGPU Intel. Configurable vía --vk-device o la env
        # GGML_VK_VISIBLE_DEVICES (ajustá el índice si tu layout difiere; default 1).
        f"export GGML_VK_VISIBLE_DEVICES={vk_device}",
        "export RNFE_CONJUNCTION_ROUTING_ENFORCED=1",
        *governance,
        "export RNFE_HOST_SENSING=1",
        # 'hashed' (CPU): este release de llama.cpp no trae llama-embedding. Para
        # embeddings en GPU: llama-server --embedding (seguimiento aparte).
        "export RNFE_MEMORY_EMBEDDINGS=hashed",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Escrito {out} (GGML_VK_VISIBLE_DEVICES={vk_device}). Cargalo con:  source {out}")
    return 0


def cmd_smoke(models_root: Path) -> int:
    cli = _find_llama_cli(models_root)
    gguf = _paths(models_root)["reasoner_gguf"]
    if cli is None or not gguf.exists():
        print("No se puede smoke: falta el binario CUDA o el GGUF. Corré --check.")
        return 1
    command = [
        str(cli), "-m", str(gguf), "-p", "Say OK.", "-n", "8", "-ngl", "99",
        "--no-warmup", "--simple-io", "--single-turn", "--no-display-prompt",
    ]
    print("== Smoke en GPU (mirá nvidia-smi en otra terminal) ==")
    try:
        out = subprocess.run(command, check=False, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}")
        return 1
    print("stdout:", (out.stdout or "").strip()[:200])
    return 0 if out.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provisión GPU llama.cpp + GGUFs.")
    parser.add_argument("--models-root", default=os.environ.get("RNFE_MODELS_ROOT", str(Path.home() / "rnfe_models")))
    parser.add_argument("--check", action="store_true", help="Diagnóstico (default, sin red).")
    parser.add_argument("--download", action="store_true", help="Descargar GGUFs (necesita red).")
    parser.add_argument("--no-embeddings", action="store_true", help="No bajar el GGUF de embeddings.")
    parser.add_argument("--write-env", metavar="PATH", help="Escribir un .env con las rutas.")
    parser.add_argument(
        "--vk-device",
        default=os.environ.get("GGML_VK_VISIBLE_DEVICES", "1"),
        help="índice de GPU Vulkan para GGML_VK_VISIBLE_DEVICES en el .env "
        "(default 1; overridea con este flag o la env GGML_VK_VISIBLE_DEVICES).",
    )
    parser.add_argument(
        "--enable-external-reasoner",
        action="store_true",
        help="Emitir activas (no comentadas) las TRES claves de gobernanza del "
        "razonador externo tier_3 (RNFE_EXTERNAL_REASONER_RUNTIME —el switch maestro— "
        "más RNFE_ALLOW_EXTERNAL_REASONER y RNFE_MAX_COMPUTE_TIER) en el .env generado. "
        "Default: comentadas / opt-in.",
    )
    parser.add_argument("--smoke", action="store_true", help="Correr una inferencia de prueba en GPU.")
    args = parser.parse_args(argv)

    models_root = Path(os.path.expanduser(args.models_root)).resolve()

    if args.download:
        return cmd_download(models_root, embeddings=not args.no_embeddings)
    if args.write_env:
        return cmd_write_env(
            models_root,
            Path(args.write_env),
            vk_device=args.vk_device,
            enable_external_reasoner=args.enable_external_reasoner,
        )
    if args.smoke:
        return cmd_smoke(models_root)
    return cmd_check(models_root)


if __name__ == "__main__":
    sys.exit(main())
