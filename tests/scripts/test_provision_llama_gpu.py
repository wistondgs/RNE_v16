"""Tests dirigidos al endurecimiento de scripts/provision_llama_gpu.py (B47 / C14 a-f).

Cubren lo verificable SIN red ni GPU:
  (a) `_safe_extractall` bloquea tar-slip (path-traversal, rutas absolutas, symlinks
      que escapan del destino) y sigue extrayendo tarballs benignos.
  (b) SHA mismatch -> `cmd_download` retorna != 0 y borra el artefacto corrupto.
  (b/c) `_verify_or_fail`: seteado -> enforce (borra + lanza); vacío -> advertencia
      honesta UNVERIFIED sin fallar.
  (d/e/f) `cmd_write_env`: preserva el contrato de nombres CUDA, resuelve el
      GGML_VK_VISIBLE_DEVICES override, y deja el gate de gobernanza del razonador
      externo como opt-in (comentado por defecto; activo con --enable-external-reasoner).

Re-obra (must-fix de la auditoría adversaria):
  1) gobernanza opt-in por defecto (no auto-escalar el gate en el .env).
  2) integridad del BINARIO llama.cpp (no solo del GGUF) vía `_verify_or_fail`.
  3) `cmd_download` verifica SIEMPRE (fuera del guard exists()): un artefacto
      preexistente corrupto aborta y no reporta "Descarga OK".
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from scripts import provision_llama_gpu as prov


# --------------------------------------------------------------------------- #
# (a) Extracción segura contra tar-slip.
# --------------------------------------------------------------------------- #


def _tar_with_member(tar_path: Path, name: str, payload: bytes = b"pwned") -> None:
    """Crea un tar.gz con un único miembro-archivo de nombre arbitrario `name`."""
    with tarfile.open(tar_path, "w:gz") as tf:
        info = tarfile.TarInfo(name=name)
        info.size = len(payload)
        import io

        tf.addfile(info, io.BytesIO(payload))


def test_safe_extractall_rejects_parent_traversal(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    tar_path = tmp_path / "evil.tar.gz"
    _tar_with_member(tar_path, "../escape.txt")

    with tarfile.open(tar_path, "r:gz") as tf:
        with pytest.raises(ValueError, match="tar inseguro"):
            prov._safe_extractall(tf, dest)

    # No debe haber escrito NADA fuera de dest.
    assert not (tmp_path / "escape.txt").exists()
    assert list(dest.iterdir()) == []


def test_safe_extractall_rejects_absolute_path(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    tar_path = tmp_path / "abs.tar.gz"
    # Ruta absoluta fuera del destino.
    _tar_with_member(tar_path, str(tmp_path / "outside" / "abs.txt"))

    with tarfile.open(tar_path, "r:gz") as tf:
        with pytest.raises(ValueError, match="tar inseguro"):
            prov._safe_extractall(tf, dest)

    assert not (tmp_path / "outside").exists()


def test_safe_extractall_rejects_escaping_symlink(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    tar_path = tmp_path / "link.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../../../etc/passwd"
        tf.addfile(info)

    with tarfile.open(tar_path, "r:gz") as tf:
        with pytest.raises(ValueError, match="link fuera del destino"):
            prov._safe_extractall(tf, dest)


def test_safe_extractall_allows_benign_tar(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    tar_path = tmp_path / "ok.tar.gz"
    _tar_with_member(tar_path, "sub/ok.txt", payload=b"hello")

    with tarfile.open(tar_path, "r:gz") as tf:
        prov._safe_extractall(tf, dest)

    extracted = dest / "sub" / "ok.txt"
    assert extracted.exists()
    assert extracted.read_bytes() == b"hello"


# --------------------------------------------------------------------------- #
# (b/c) Verificación de integridad fail-closed.
# --------------------------------------------------------------------------- #


def test_verify_or_fail_mismatch_deletes_and_raises(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gguf"
    artifact.write_bytes(b"real-content")
    real = prov._sha256(artifact)
    wrong = "0" * 64
    assert real != wrong

    with pytest.raises(prov.IntegrityError, match="fail-closed"):
        prov._verify_or_fail(artifact, wrong, "reasoner_gguf")

    # Fail-closed: el artefacto corrupto se borra del disco.
    assert not artifact.exists()


def test_verify_or_fail_match_keeps_file(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gguf"
    artifact.write_bytes(b"real-content")
    real = prov._sha256(artifact)

    prov._verify_or_fail(artifact, real, "reasoner_gguf")  # no debe lanzar
    assert artifact.exists()


def test_verify_or_fail_empty_hash_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "embed.gguf"
    artifact.write_bytes(b"embed-content")

    prov._verify_or_fail(artifact, "", "embed_gguf")  # no debe lanzar
    assert artifact.exists()

    out = capsys.readouterr().out
    assert "UNVERIFIED" in out
    assert "embed_gguf" in out
    # Imprime el hash observado para poder pinnearlo.
    assert prov._sha256(artifact) in out


def test_cmd_download_fail_closed_on_reasoner_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models_root = tmp_path / "models"

    def fake_hf_download(repo: str, filename: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"tampered-gguf")
        return dest

    monkeypatch.setattr(prov, "_hf_download", fake_hf_download)
    # Digest observado incorrecto -> mismatch contra REASONER_SHA256 pinneado.
    monkeypatch.setattr(prov, "_sha256", lambda path: "deadbeef" * 8)

    reasoner_path = prov._paths(models_root)["reasoner_gguf"]

    rc = prov.cmd_download(models_root, embeddings=False)

    assert rc != 0
    # El GGUF manipulado NO queda en disco.
    assert not reasoner_path.exists()


def test_cmd_download_fail_closed_on_preexisting_corrupt_reasoner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # (must-fix 3) Un GGUF PREEXISTENTE corrupto NO debe saltear _verify_or_fail via
    # exists()->skip: cmd_download aborta (rc!=0) sin imprimir "Descarga OK", aunque
    # no se descargue nada en esta corrida.
    models_root = tmp_path / "models"
    reasoner_path = prov._paths(models_root)["reasoner_gguf"]
    reasoner_path.parent.mkdir(parents=True, exist_ok=True)
    # Contenido arbitrario: su hash real != REASONER_SHA256 pinneado.
    reasoner_path.write_bytes(b"corrupt-preexisting-artifact")

    # Prueba que NO se intenta descargar (el archivo ya existe).
    def _boom(*args: object, **kwargs: object) -> Path:
        raise AssertionError("no debe descargar: el artefacto ya existe")

    monkeypatch.setattr(prov, "_hf_download", _boom)

    rc = prov.cmd_download(models_root, embeddings=False)

    assert rc != 0
    out = capsys.readouterr().out
    assert "Descarga OK" not in out
    # Fail-closed: el artefacto corrupto se borró del disco.
    assert not reasoner_path.exists()


# --------------------------------------------------------------------------- #
# (d/e/f) write_env: contrato de nombres, override de device, gobernanza.
# --------------------------------------------------------------------------- #


def _write_env_lines(tmp_path: Path, **kwargs) -> list[str]:
    out = tmp_path / ".env.local"
    rc = prov.cmd_write_env(tmp_path / "models", out, **kwargs)
    assert rc == 0
    return out.read_text(encoding="utf-8").splitlines()


def test_write_env_vk_device_override(tmp_path: Path) -> None:
    lines = _write_env_lines(tmp_path, vk_device="3")
    assert "export GGML_VK_VISIBLE_DEVICES=3" in lines
    assert "export GGML_VK_VISIBLE_DEVICES=1" not in lines


def test_write_env_vk_device_default_is_1(tmp_path: Path) -> None:
    lines = _write_env_lines(tmp_path)
    assert "export GGML_VK_VISIBLE_DEVICES=1" in lines


def test_write_env_external_reasoner_opt_in_commented_by_default(tmp_path: Path) -> None:
    # (must-fix 1) El gate de gobernanza NO se auto-habilita: por defecto las TRES
    # claves de armado salen COMENTADAS (opt-in), nunca activas. La MAESTRA es
    # RNFE_EXTERNAL_REASONER_RUNTIME (la que leen el camino vivo scenario_runner.py y la
    # admisión policy.py, y de la que life_kernel deriva allow_external): dejarla activa
    # por defecto armaría el razonador aunque las otras dos estén comentadas.
    lines = _write_env_lines(tmp_path)
    assert "export RNFE_EXTERNAL_REASONER_RUNTIME=1" not in lines
    assert "export RNFE_ALLOW_EXTERNAL_REASONER=1" not in lines
    assert "export RNFE_MAX_COMPUTE_TIER=tier_3_external" not in lines
    text = "\n".join(lines)
    assert "# export RNFE_EXTERNAL_REASONER_RUNTIME=1" in text
    assert "# export RNFE_ALLOW_EXTERNAL_REASONER=1" in text
    assert "# export RNFE_MAX_COMPUTE_TIER=tier_3_external" in text
    # Nota explicativa de una línea para el operador.
    assert "habilitar el razonador externo tier_3" in text


def test_write_env_external_reasoner_active_with_flag(tmp_path: Path) -> None:
    # (must-fix 1) Con --enable-external-reasoner las TRES claves se emiten activas.
    lines = _write_env_lines(tmp_path, enable_external_reasoner=True)
    assert "export RNFE_EXTERNAL_REASONER_RUNTIME=1" in lines
    assert "export RNFE_ALLOW_EXTERNAL_REASONER=1" in lines
    assert "export RNFE_MAX_COMPUTE_TIER=tier_3_external" in lines
    text = "\n".join(lines)
    assert "# export RNFE_ALLOW_EXTERNAL_REASONER=1" not in text


def test_main_write_env_external_reasoner_flag_activates(
    tmp_path: Path,
) -> None:
    # (must-fix 1) El flag del CLI llega a cmd_write_env y activa las claves.
    out = tmp_path / ".env.enabled"
    rc = prov.main(
        [
            "--write-env",
            str(out),
            "--models-root",
            str(tmp_path / "models"),
            "--enable-external-reasoner",
        ]
    )
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "export RNFE_EXTERNAL_REASONER_RUNTIME=1" in lines
    assert "export RNFE_ALLOW_EXTERNAL_REASONER=1" in lines
    assert "export RNFE_MAX_COMPUTE_TIER=tier_3_external" in lines


def test_main_write_env_external_reasoner_default_commented(tmp_path: Path) -> None:
    # (must-fix 1) Sin el flag, el CLI deja las TRES claves comentadas — incluido el
    # switch maestro RNFE_EXTERNAL_REASONER_RUNTIME: `source` del .env por defecto NO
    # debe armar el razonador externo.
    out = tmp_path / ".env.default"
    rc = prov.main(["--write-env", str(out), "--models-root", str(tmp_path / "models")])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "export RNFE_EXTERNAL_REASONER_RUNTIME=1" not in lines
    assert "export RNFE_ALLOW_EXTERNAL_REASONER=1" not in lines
    assert "export RNFE_MAX_COMPUTE_TIER=tier_3_external" not in lines


def test_write_env_preserves_cuda_contract(tmp_path: Path) -> None:
    # (d) NO renombrar: el config lee estas claves con nombre CUDA.
    text = "\n".join(_write_env_lines(tmp_path))
    assert "export RNFE_EXTERNAL_REASONER_BACKEND=cuda" in text
    assert "RNFE_LLAMA_CLI_CUDA=" in text
    # La deuda "vulkan-bajo-nombre-CUDA" queda inequívoca en el .env generado.
    assert "backend real: vulkan" in text


def test_main_write_env_uses_env_vk_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (e) El override por env GGML_VK_VISIBLE_DEVICES se propaga al .env via el default del CLI.
    monkeypatch.setenv("GGML_VK_VISIBLE_DEVICES", "7")
    out = tmp_path / ".env.fromenv"
    rc = prov.main(["--write-env", str(out), "--models-root", str(tmp_path / "models")])
    assert rc == 0
    assert "export GGML_VK_VISIBLE_DEVICES=7" in out.read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------- #
# (must-fix 2) Integridad del BINARIO llama.cpp Vulkan (no solo del GGUF).
# --------------------------------------------------------------------------- #


def test_llama_vulkan_sha256_empty_by_default() -> None:
    # La constante existe con la misma semántica que EMBED_SHA256 (vacía = UNVERIFIED).
    assert prov.LLAMA_VULKAN_SHA256 == ""


def test_download_llama_vulkan_fail_closed_on_bad_binary_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Con LLAMA_VULKAN_SHA256 pinneado que NO coincide -> fail-closed: el tar se
    # borra y NO se extrae el binario (espejo del GGUF).
    import urllib.request

    models_root = tmp_path / "models"

    def fake_urlretrieve(url: str, dest: str) -> None:
        _tar_with_member(Path(dest), "build/bin/llama-cli", payload=b"native-binary")

    monkeypatch.setattr(urllib.request, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(prov, "LLAMA_VULKAN_SHA256", "0" * 64)

    cli = prov._download_llama_vulkan(models_root)

    assert cli is None
    dest_dir = models_root / "tools" / "llama.cpp" / "build-vulkan"
    # El tar manipulado se borró (unlink de _verify_or_fail) y NO se extrajo el binario.
    assert not (dest_dir / prov.LLAMA_VULKAN_ASSET).exists()
    assert not list(dest_dir.rglob("llama-cli"))


def test_download_llama_vulkan_unverified_binary_warns_but_extracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Con LLAMA_VULKAN_SHA256 vacío (default) -> UNVERIFIED explícito pero sigue:
    # extrae y encuentra el llama-cli (mismo comportamiento honesto que el embed).
    import urllib.request

    monkeypatch.delenv("RNFE_LLAMA_CLI_CUDA", raising=False)
    models_root = tmp_path / "models"

    def fake_urlretrieve(url: str, dest: str) -> None:
        _tar_with_member(Path(dest), "build/bin/llama-cli", payload=b"native-binary")

    monkeypatch.setattr(urllib.request, "urlretrieve", fake_urlretrieve)
    # LLAMA_VULKAN_SHA256 queda en su default vacío.

    cli = prov._download_llama_vulkan(models_root)

    out = capsys.readouterr().out
    assert "UNVERIFIED" in out
    assert "llama.cpp Vulkan" in out
    assert cli is not None
    assert cli.name == "llama-cli"


# --------------------------------------------------------------------------- #
# (re-obra 2) Binario PREEXISTENTE sin verificar + higiene de vk_device.
# --------------------------------------------------------------------------- #


def test_cmd_download_warns_on_preexisting_unverified_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # (must-fix 2 residual) Un binario llama.cpp PREEXISTENTE (no bajado en esta corrida,
    # resuelto por _find_llama_cli) no pasa por _verify_or_fail: cmd_download debe ADVERTIR
    # UNVERIFIED sobre el binario que el runtime ejecutará, no dejarlo pasar en silencio.
    monkeypatch.delenv("RNFE_LLAMA_CLI_CUDA", raising=False)
    models_root = tmp_path / "models"
    reasoner = prov._paths(models_root)["reasoner_gguf"]
    reasoner.parent.mkdir(parents=True, exist_ok=True)
    reasoner.write_bytes(b"ok-gguf")  # preexiste -> no se descarga
    monkeypatch.setattr(prov, "_verify_or_fail", lambda *a, **k: None)  # neutraliza el GGUF
    cli = models_root / "tools" / "llama.cpp" / "build-vulkan" / "bin" / "llama-cli"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("#!/bin/sh\n")  # binario preexistente

    rc = prov.cmd_download(models_root, embeddings=False)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Descarga OK" in out
    assert "UNVERIFIED [binario llama.cpp]" in out


def test_write_env_rejects_vk_device_injection(tmp_path: Path) -> None:
    # (higiene, hallazgo de la auditoría) vk_device con salto de línea NO debe inyectar
    # líneas `export` en el .env: se rechaza (rc 2) y no se escribe el archivo envenenado.
    out = tmp_path / ".env.inj"
    rc = prov.cmd_write_env(
        tmp_path / "models",
        out,
        vk_device="1\nexport RNFE_EXTERNAL_REASONER_RUNTIME=1",
    )
    assert rc == 2
    if out.exists():
        assert "export RNFE_EXTERNAL_REASONER_RUNTIME=1" not in out.read_text(encoding="utf-8")


def test_write_env_accepts_multi_device_list(tmp_path: Path) -> None:
    # Una lista numérica válida (p.ej. '0,1') se acepta y se emite tal cual.
    lines = _write_env_lines(tmp_path, vk_device="0,1")
    assert "export GGML_VK_VISIBLE_DEVICES=0,1" in lines
