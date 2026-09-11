// hello-iw5: prints to each player once they spawn. The IW5 counterpart of hello-zm, used to
// exercise the build pipeline for game iw5. Uses only engine builtins (waittill, thread,
// iprintln) that IW5 shares with T6, so gsc-tool -g iw5 compiles it offline without include files.

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
    self iprintln( "^2hello-iw5 loaded through the Plutonium Agent Toolkit" );
}
