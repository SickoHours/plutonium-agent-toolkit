`<REPO>/examples/hello-zm-two` contains a round announcer (`announce_round` in
`scripts/round_announcer.gsc`). Port that feature into a copy of `<REPO>/examples/hello-zm` so one
mod both greets each player on spawn and announces each round. Work in `<RUN>/bench-04-port-feature/`:
copy the hello-zm project there, add the feature, then build and verify the result with the
toolkit, with every job in its own new directory under that path. Report the SHA-256 of the
built `mod.ff`, which scripts it contains, and what remains unverified without a game.
