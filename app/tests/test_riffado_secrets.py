import stat

from app.install import riffado


def test_gen_secrets_lengths_with_injected_rng():
    s = riffado.gen_secrets(rng=lambda n: "x" * (2 * n))  # mimic token_hex(n) -> 2n chars
    assert s["BETTER_AUTH_SECRET"] == "x" * 64
    assert s["ENCRYPTION_KEY"] == "x" * 64
    assert s["POSTGRES_PASSWORD"] == "x" * 48
    assert set(s) == {"BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"}


def test_gen_secrets_default_rng_is_hex():
    s = riffado.gen_secrets()
    assert len(s["BETTER_AUTH_SECRET"]) == 64
    assert all(c in "0123456789abcdef" for c in s["POSTGRES_PASSWORD"])


def test_missing_secret_keys_blank_counts_as_missing():
    assert set(riffado.missing_secret_keys("")) == {
        "BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"
    }
    text = "RIFFADO_VERSION=0.5.6\nPOSTGRES_PASSWORD=\nBETTER_AUTH_SECRET=already\nENCRYPTION_KEY=also\n"
    assert riffado.missing_secret_keys(text) == ["POSTGRES_PASSWORD"]  # blank value -> missing
    full = "POSTGRES_PASSWORD=p\nBETTER_AUTH_SECRET=a\nENCRYPTION_KEY=e\n"
    assert riffado.missing_secret_keys(full) == []


def test_fill_secrets_only_missing():
    existing = "BETTER_AUTH_SECRET=keep\nENCRYPTION_KEY=\n"  # POSTGRES absent, ENC blank
    gen = {"BETTER_AUTH_SECRET": "new", "ENCRYPTION_KEY": "newenc", "POSTGRES_PASSWORD": "newpw"}
    out = riffado.fill_secrets(existing, gen)
    assert out == {"ENCRYPTION_KEY": "newenc", "POSTGRES_PASSWORD": "newpw"}  # BETTER_AUTH kept


def test_write_env_idempotent_preserves_and_no_rotation(tmp_path):
    env = tmp_path / ".env"
    env.write_text("RIFFADO_VERSION=0.5.6\nPOSTGRES_PASSWORD=livepw\nBETTER_AUTH_SECRET=\nENCRYPTION_KEY=\n")
    gen = {"BETTER_AUTH_SECRET": "A", "ENCRYPTION_KEY": "E", "POSTGRES_PASSWORD": "ROTATED"}
    written = riffado.write_env_idempotent(env, gen)
    assert written == ["BETTER_AUTH_SECRET", "ENCRYPTION_KEY"]  # POSTGRES not rotated
    text = env.read_text()
    assert "RIFFADO_VERSION=0.5.6" in text
    assert "POSTGRES_PASSWORD=livepw" in text and "ROTATED" not in text
    assert "BETTER_AUTH_SECRET=A" in text and "ENCRYPTION_KEY=E" in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600  # envfile.upsert chmods
    # re-run writes nothing
    assert riffado.write_env_idempotent(env, gen) == []


def test_write_env_idempotent_creates_when_absent(tmp_path):
    env = tmp_path / "riffado.env"
    written = riffado.write_env_idempotent(env, {"BETTER_AUTH_SECRET": "A", "ENCRYPTION_KEY": "E", "POSTGRES_PASSWORD": "P"})
    assert set(written) == {"BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"}
    assert env.exists()
