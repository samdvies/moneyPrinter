"""Test-support stub: a module inside the allowed namespace that has no ``on_tick``.

Used exclusively by ``test_module_without_on_tick_raises_strategy_load_error``
to verify that the loader's structural ``StrategyModule`` check fires when
``on_tick`` is absent.  Not a real strategy; do not use in production.
"""
