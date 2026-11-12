-- One database per service inside the single local Postgres instance.
-- Runs once, on first initialisation of the Compose volume.
CREATE DATABASE buyer;
CREATE DATABASE registry;
CREATE DATABASE sellers;
CREATE DATABASE verifund;
CREATE DATABASE verifund_agent;
CREATE DATABASE orchestrator;
