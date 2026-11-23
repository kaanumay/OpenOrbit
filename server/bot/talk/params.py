"""Tunable numbers of the Normal mode chat engine (tools/chat_lab tune.py searches these; the best values found are written here)."""

P = dict(
    # --- who answers a human message
    p_addressed_question=0.99,      # a bot named / spoken to with a question answers
    p_addressed_other=0.97,          # a bot named / spoken to with a statement, greeting ... answers
    p_open_question=0.15,           # a question to nobody: chance per listener that he answers (14 listeners -> 80%, 4 -> 37%)
    p_second_answer=0.18,           # a second bot adds its own answer to an open question
    p_greet_reply=0.13,            # a greeting to all: chance per listener of a greeting back
    p_greet_extra=0.25,             # a second greeting back
    p_statement_reply=0.045,        # a statement to all (not a question): chance per listener of a reaction
    p_laugh_reply=0.12,             # a lone laugh gets a reaction
    p_bye_reply=0.5,
    p_back_reply=0.45,              # "geldim / back" gets a wb
    p_bot_accusation=0.85,          # "are you a bot": someone denies it
    p_insult_reply=0.75,            # an insult aimed at a bot: it answers (scaled by aggression)
    p_askback=0.35,                 # a personal answer ends with "sen?" / "you?"
    p_ack=0.55,                     # the asker acknowledges an answer ("ok ty")
    p_share=0.45,                   # the asker of a personal question shares his own answer ("ben 20")
    # --- bot to bot
    p_bot_reply=0.72,               # a bot's question gets an answer from another bot (0.65 before 2026-11-23: 56% of questions unanswered)
    p_bot_react=0.3,                # a bot's statement gets a reaction (0.22 before 2026-11-23: "sıkıldım", "uykum var" went unanswered)
    p_event_react=0.6,              # a bot's news (level up, new ship, boss) gets a gz
    p_followup=0.25,                # the asker questions a game answer ("u sure?", "why?") instead of a plain thanks
    p_opinion=0.35,                 # a third bot adds its view to a game answer (agrees, another map, disagrees)
    p_defend=0.4,                   # the one disagreed with holds his ground ("trust me")
    max_depth=5,                    # lines in one bot-to-bot exchange (the opener counts): question, answer, "why?", reason, thanks
    channel_topic_sec=1200.0,       # the same opener (or question topic) in one channel, by anyone, at most once in this time
    spontaneous_per_min=0.46,       # expected spontaneous openers per minute (scaled by online bots / 20, capped); 0.55 before
    #                                 2026-11-23: fewer topics now that each one runs longer (follow-ups, second opinions)
    quiet_after_human=60.0,         # bots do not open new topics this long after a human wrote
    bot_gap_sec=420.0,              # minimum gap between two spontaneous openers of the same bot
    # --- timing (seconds)
    read_cps=18.0,                  # reading speed (characters per second)
    think_mu=1.6, think_sigma=0.7,  # thinking time before typing (lognormal-ish)
    busy_extra=9.0,                 # extra delay when the bot is fighting
    late_reply=0.06,                # chance of a much later reply (afk for a moment)
    split_gap=(1.2, 3.5),           # gap between the two halves of a split message
    # --- surface
    opt=0.5,                        # chance of an optional [part]
    similar_window=400,             # recent lines checked for near repeats (all bots)
    repeat_sec=2700.0,              # the same line (two words or more) is not written again within this time, by anyone
    complaint_sec=1200.0,           # between two complaining openers (lag, uri, aliens) in the whole chat
    tries=6,                        # pattern draws until a fresh line is found
)
