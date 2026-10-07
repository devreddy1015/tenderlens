from django.core.management.base import BaseCommand

from intel import prices
from intel.models import HistoricalAward


class Command(BaseCommand):
    help = "Refresh CPI and exchange rates (World Bank WDI) for India, the US and every country in the award data"

    def add_arguments(self, parser):
        parser.add_argument("countries", nargs="*", help="extra ISO-2 country codes")
        parser.add_argument(
            "--reprice",
            action="store_true",
            help="then recompute the real-rupee amounts of every award row",
        )

    def handle(self, *args, **opts):
        awards = HistoricalAward.objects.all()
        countries = prices.rate_countries(
            set(opts["countries"]) | set(awards.values_list("country", flat=True).distinct()),
            awards.values_list("currency", flat=True).distinct(),
        )
        n = prices.refresh(countries)
        self.stdout.write(
            f"stored {n} observations for {len(set(countries) | {'IN', 'US'})} countries"
        )
        if opts["reprice"]:
            changed = prices.reprice()
            self.stdout.write(f"repriced {changed} rows")
