# MRMix Profile Plot

## What This Plot Is For

This plot shows the estimated valid-IV proportion `pi0` from MRMix across candidate causal effects `theta`, helping assess whether the final theta estimate lies in a region strongly supported by the model.

## What Is In The Plot

- The x-axis is the candidate causal effect `theta`, a range of possible MR beta values.
- The y-axis is the estimated valid-IV proportion `pi0`, meaning the proportion of instruments the model estimates as valid at that `theta`.
- The black curve `#333333` is the profile curve, showing `pi0` across different `theta` values.
- The orange vertical line `#D55E00` is the MRMix theta estimate, the final reported beta location.
- This plot has no confidence-interval shading; the key visual comparison is between the black profile curve and the orange estimate line.

## How To Read It

Look first for the peak or high plateau of the black curve. Those regions indicate that more SNPs are explained as valid IVs at that `theta`. Then check whether the orange estimate line falls near a high point. If the black curve is flat, has multiple competing peaks, or the orange line falls in a low-support region, the plot provides less clear support for the beta location.

## Do Not Interpret From This Plot Alone

This plot explains the MRMix profile and the theta estimate location. Final interpretation should also use beta, standard error, p value, number of SNPs, mixture-model output, and results from other MR methods.
