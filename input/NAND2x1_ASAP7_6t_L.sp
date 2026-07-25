.SUBCKT NAND2x1_ASAP7_6t_L A B VDD VSS Y
MM3 net16 A VSS VSS nmos_lvt w=108.00n l=20n nfin=4
MM2 Y B net16 VSS nmos_lvt w=108.00n l=20n nfin=4
MM1 Y B VDD VDD pmos_lvt w=54.0n l=20n nfin=2
MM0 Y A VDD VDD pmos_lvt w=54.0n l=20n nfin=2
.ENDS NAND2x1_ASAP7_6t_L
