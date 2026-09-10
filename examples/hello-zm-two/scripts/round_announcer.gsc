// round_announcer: prints the round number to every player when a round starts.
// A second, independent example feature: the benchmark's port task moves
// announce_round into hello-zm. Uses only engine builtins and the level's own
// start_of_round notify, so gsc-tool compiles it offline without include files.

main()
{
    level thread announce_round();
}

announce_round()
{
    for ( ;; )
    {
        level waittill( "start_of_round" );
        iprintlnbold( "^3Round " + level.round_number + " starts" );
    }
}
