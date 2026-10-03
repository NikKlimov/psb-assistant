from psb_assistant.parsers.cards import CardParser
from psb_assistant.parsers.deposits import DepositParser
from psb_assistant.parsers.loans import LoanParser

PARSERS = {"deposits": DepositParser(), "loans": LoanParser(), "cards": CardParser()}
