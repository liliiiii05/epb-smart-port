
from port.views import get_shift_interval, temps_par_shift
from datetime import datetime, timedelta

base = datetime(2026, 4, 30, 0, 0, 0)
debut = base
fin = base + timedelta(hours=28.8)
shifts = temps_par_shift(debut, fin)

for shift, duree in shifts.items():
    print(f'{shift}: {duree:.1f}h')
print(f'Total: {sum(shifts.values()):.1f}h')
