.SUBCKT AND2x2_ASAP7_6t_L A B VDD VSS Y
MM4 Y net10 VDD VDD pmos_lvt w=108.00n l=20n nfin=4
MM1 net10 B VDD VDD pmos_lvt w=27.0n l=20n nfin=1
MM0 net10 A VDD VDD pmos_lvt w=27.0n l=20n nfin=1
MM5 Y net10 VSS VSS nmos_lvt w=108.00n l=20n nfin=4
MM3 net20 A VSS VSS nmos_lvt w=54.0n l=20n nfin=2
MM2 net10 B net20 VSS nmos_lvt w=54.0n l=20n nfin=2
.ENDS AND2x2_ASAP7_6t_L
