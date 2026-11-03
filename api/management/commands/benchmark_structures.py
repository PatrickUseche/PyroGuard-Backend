from django.core.management.base import BaseCommand, CommandError

from api.benchmarks import CASES, format_table, run_benchmarks


class Command(BaseCommand):
    help = (
        "Mide cada estructura de api/structures frente a la consulta equivalente en la base de datos. "
        "Crea datos sintéticos dentro de una transacción que se deshace al terminar: no deja nada en la base."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sizes",
            default="1000,10000",
            help="Cantidad de lecturas de cada ronda, separadas por comas (por defecto 1000,10000).",
        )
        parser.add_argument("--repeat", type=int, default=200, help="Repeticiones de la estructura (por defecto 200).")
        parser.add_argument("--db-repeat", type=int, default=20, help="Repeticiones de la consulta (por defecto 20).")
        parser.add_argument("--seed", type=int, default=1, help="Semilla de los datos sintéticos.")
        parser.add_argument("--markdown", action="store_true", help="Imprime la tabla en Markdown (para docs/).")

    def handle(self, *args, **options):
        try:
            sizes = [int(part) for part in options["sizes"].split(",") if part.strip()]
        except ValueError:
            raise CommandError("--sizes debe ser una lista de enteros separados por comas.") from None
        if not sizes or any(size < 100 for size in sizes):
            raise CommandError("Cada tamaño debe ser de al menos 100 lecturas.")
        if options["repeat"] < 1 or options["db_repeat"] < 1:
            raise CommandError("--repeat y --db-repeat deben ser mayores o iguales que 1.")

        self.stderr.write(f"Midiendo {len(CASES)} casos con {sizes} lecturas (puede tardar un poco)...")
        results = run_benchmarks(
            sizes, repeat=options["repeat"], db_repeat=options["db_repeat"], seed=options["seed"]
        )
        self.stdout.write(format_table(results, markdown=options["markdown"]))
