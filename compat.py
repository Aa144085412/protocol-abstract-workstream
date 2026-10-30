"""
compat
======
Small compatibility shim so the app runs across a wide range of Streamlit
versions. Older Streamlit (e.g. the 1.12 that ships with some Anaconda installs)
lacks ``st.divider()`` and rejects newer keyword args like ``use_container_width``,
``type=``, or ``text=`` on ``st.progress``.

This module:
  1. Backfills ``st.divider`` if missing.
  2. Wraps common widget functions so that keyword arguments the installed
     version does not understand are silently dropped (you lose the cosmetic
     feature, but the app keeps running).

On a modern Streamlit this is a no-op: every kwarg the app passes is valid, so
nothing is filtered. Import this BEFORE building any UI.
"""

from __future__ import annotations

import inspect

import streamlit as st

# Functions whose newer keyword args we want to tolerate on old Streamlit.
_PATCH_TARGETS = [
    "button", "download_button", "form_submit_button", "dataframe", "progress",
    "metric", "selectbox", "text_input", "text_area", "number_input",
    "file_uploader", "checkbox", "info", "success", "warning", "error",
    "caption", "subheader", "header", "markdown", "json", "expander", "tabs",
    "columns", "progress", "container", "multiselect",
]


def _patch(name: str) -> None:
    orig = getattr(st, name, None)
    if orig is None or getattr(orig, "_labagent_patched", False):
        return
    try:
        params = inspect.signature(orig).parameters
    except (ValueError, TypeError):
        return
    # If the function accepts **kwargs we cannot tell what's unsupported; leave it.
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return
    allowed = set(params)

    def wrapper(*args, _orig=orig, _allowed=allowed, **kwargs):
        clean = {k: v for k, v in kwargs.items() if k in _allowed}
        return _orig(*args, **clean)

    wrapper._labagent_patched = True  # type: ignore[attr-defined]
    setattr(st, name, wrapper)


def apply() -> None:
    # --- backfill APIs missing on older Streamlit (e.g. 1.12) ---
    if not hasattr(st, "divider"):
        st.divider = lambda: st.markdown("---")  # type: ignore[attr-defined]

    if not hasattr(st, "rerun"):
        # st.rerun arrived in 1.27; older versions used experimental_rerun.
        _rerun = getattr(st, "experimental_rerun", None)
        if _rerun is not None:
            st.rerun = _rerun  # type: ignore[attr-defined]
        else:  # last resort: no-op (script will just continue)
            st.rerun = lambda: None  # type: ignore[attr-defined]

    if not hasattr(st, "data_editor"):
        # editable grid arrived as experimental_data_editor (1.19) then
        # data_editor (1.23). On anything older, fall back to a read-only table
        # that returns the input unchanged so forms still submit.
        _ed = getattr(st, "experimental_data_editor", None)
        if _ed is not None:
            st.data_editor = _ed  # type: ignore[attr-defined]
        else:
            def _ro_editor(data=None, **_kw):
                try:
                    st.dataframe(data)
                    st.caption("(Editing needs Streamlit >= 1.23 — showing read-only. "
                               "Run in the modern env to edit here.)")
                except Exception:
                    pass
                return data
            st.data_editor = _ro_editor  # type: ignore[attr-defined]

    for name in set(_PATCH_TARGETS):
        _patch(name)
