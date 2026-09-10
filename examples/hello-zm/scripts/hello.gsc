// hello-zm: prints to each player once they spawn. Used by the toolkit's
// first-run qualification. Uses only engine builtins (waittill, thread,
// iprintln) so gsc-tool compiles it offline without any T6 include files.

main()
{
    level thread on_player_connect();
}

on_player_connect()
{
    for ( ;; )
    {
        level waittill( "connected", player );
        player thread on_player_spawned();
    }
}

on_player_spawned()
{
    self waittill( "spawned_player" );
    self iprintln( "^2hello-zm loaded through the Plutonium Agent Toolkit" );
}
