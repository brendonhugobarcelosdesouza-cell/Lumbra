"""Testes de PasswordHasher (Argon2id) e InMemoryUserStore."""

import pytest

from lumbra.adapters.security.passwords import PasswordHasher
from lumbra.adapters.users.in_memory import InMemoryUserStore
from lumbra.ports.users import DuplicateEmailError, UserNotFoundError


class TestPasswords:
    def test_hash_and_verify(self):
        hasher = PasswordHasher()
        digest = hasher.hash("senha-muito-secreta")
        assert digest.startswith("$argon2id$")
        assert hasher.verify(digest, "senha-muito-secreta") is True
        assert hasher.verify(digest, "senha-errada") is False

    def test_verify_never_raises_on_garbage(self):
        assert PasswordHasher().verify("nao-e-um-hash", "x") is False

    def test_hashes_are_salted(self):
        hasher = PasswordHasher()
        assert hasher.hash("mesma-senha") != hasher.hash("mesma-senha")


class TestUserStore:
    async def test_create_and_lookup(self):
        store = InMemoryUserStore()
        user = await store.create(email="Brendon@Example.com", password_hash="h")
        assert user.email == "brendon@example.com"  # normalizado
        assert (await store.get_by_email("BRENDON@example.COM")).id == user.id
        assert (await store.get_by_id(user.id)).email == user.email

    async def test_duplicate_email_rejected(self):
        store = InMemoryUserStore()
        await store.create(email="a@b.com", password_hash="h")
        with pytest.raises(DuplicateEmailError):
            await store.create(email="A@B.com", password_hash="h2")

    async def test_not_found(self):
        store = InMemoryUserStore()
        with pytest.raises(UserNotFoundError):
            await store.get_by_email("ghost@x.com")
