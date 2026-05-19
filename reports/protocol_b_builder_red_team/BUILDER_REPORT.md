# Protocol B — builder report

**Rôle :** Builder (Agent 47)

## Position initiale (optimiste contrôlée)

Le builder note des rejets BH cohérents avec l’hypothèse « choc de volume → vol/risk forward » sur BTC et ETH :

- BTC `vol_z20_high` : 18 événements, 3 cellules BH (dont return et vol post_7).  
- ETH `vol_z60_high` : 15 événements, 3 cellules BH sur vol post_3/post_7.

Le builder **propose** : `candidate for further validation` sur BTC vol_z20_high uniquement, en insistant que c’est un proxy de vol, pas un alpha directionnel.

## Ce que le builder a bien fait

- Cache-only, provenance SHA dans JSON, hold-out activé.  
- Variantes pré-enregistrées non retunées.

## Ce que le builder a sous-estimé

- Placebos shift/shuffle à p=1.0 sur la cellule alignée.  
- Hold-out `oos_survives: false`.  
- Red team historique volume shock = **fail**.  
- SOL manquant → généralisation multi-actif non prouvée.
