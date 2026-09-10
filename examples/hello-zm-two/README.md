# hello-zm-two

A second minimal T6 Zombies mod, independent of `hello-zm`. It announces each round's number to
every player when the round starts, using only engine builtins and the level's own
`start_of_round` notify, so it compiles offline without include files.

It exists so that `tools/benchmark/` has a port task with a real source and target: move
`announce_round` from here into `hello-zm` and build the result. Build it alone with:

```sh
pat project build examples/hello-zm-two/project.json --output ../jobs/round-build-001 --json
```

Like `hello-zm`, it has been compiled and linked with the real tools; seeing the message in game
is a separate, human-authorized step.
