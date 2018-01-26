import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, average_precision_score,
                             cohen_kappa_score, f1_score, matthews_corrcoef,
                             precision_recall_curve, roc_auc_score, roc_curve)
from sklearn.model_selection import StratifiedKFold

from atm.constants import *


def rank_n_accuracy(y_true, y_prob_mat, n=0.33):
    """
    Compute how often the true label is one of the top n predicted classes
    for each training example.
    If n is an integer, consider the top n predictions for each example.
    If n is a float, it represents a proportion of the top predictions.
    This metric is only really useful when the total number of classes is large.
    """
    n_classes = y_prob_mat.shape[1]
    if n < 1:
        # round to nearest int before casting
        n = int(round(n_classes * n))

    # sort the rankings in descending order, then take the top n
    rankings = np.argsort(-y_prob_mat)
    rankings = rankings[:, :n]

    num_samples = len(y_true)
    correct_sample_count = 0.0   # force floating point math

    for i in range(num_samples):
        if y_true[i] in rankings[i, :]:
            correct_sample_count += 1

    return correct_sample_count / num_samples


def get_per_class_matrix(y, classes=None):
    """
    Create a (num_classes x num_examples) binary matrix representation of the
    true and predicted y values.
    If classes is None, class values will be extracted from y. Values that are
    not present at all will not receive a column -- this is to allow computation
    of per-class roc_auc scores without error.
    """
    classes = classes or np.unique(y)
    y_bin = np.zeros((len(y), len(classes)))
    for i, cls in enumerate(classes):
        y_bin[:, i] = (y == cls).astype(int)
    return y_bin


def get_pr_roc_curves(y_true, y_pred_probs):
    """
    Compute precision/recall and receiver operating characteristic metrics for a
    binary class label.

    y_true: series of true class labels (only 1 or 0)
    y_pred_probs: series of probabilities generated by the model for the label
        class 1
    """
    results = {}
    roc = roc_curve(y_true, y_pred_probs, pos_label=1)
    results[Metrics.ROC_CURVE] = {
        'fprs': list(roc[0]),
        'tprs': list(roc[1]),
        'thresholds': list(roc[2]),
    }

    pr = precision_recall_curve(y_true, y_pred_probs, pos_label=1)
    results[Metrics.PR_CURVE] = {
        'precisions': list(pr[0]),
        'recalls': list(pr[1]),
        'thresholds': list(pr[2]),
    }

    return results


def get_metrics_binary(y_true, y_pred, y_pred_probs, include_curves=False):
    results = {
        Metrics.ACCURACY: accuracy_score(y_true, y_pred),
        Metrics.COHEN_KAPPA: cohen_kappa_score(y_true, y_pred),
        Metrics.F1: f1_score(y_true, y_pred),
        Metrics.MCC: matthews_corrcoef(y_true, y_pred),
        Metrics.ROC_AUC: np.nan,
        Metrics.AP: np.nan,
    }

    # if possible, compute PR and ROC curve metrics
    all_labels_same = len(np.unique(y_true)) == 1
    any_probs_nan = np.any(np.isnan(y_pred_probs))
    if not any_probs_nan:
        # AP can be computed even if all labels are the same
        y_true_bin = get_per_class_matrix(y_true, range(2))
        results[Metrics.AP] = average_precision_score(y_true_bin, y_pred_probs)

        if not all_labels_same:
            results[Metrics.ROC_AUC] = roc_auc_score(y_true_bin, y_pred_probs)

        # if necessary, compute point-by-point precision/recall and ROC curve data
        if include_curves:
            results.update(get_pr_roc_curves(y_true, y_pred_probs[:, 1]))

    return results


def get_metrics_multiclass(y_true, y_pred, y_pred_probs,
                           include_per_class=False, include_curves=False):
    results = {
        Metrics.ACCURACY: accuracy_score(y_true, y_pred),
        Metrics.COHEN_KAPPA: cohen_kappa_score(y_true, y_pred),
        Metrics.F1_MICRO: f1_score(y_true, y_pred, average='micro'),
        Metrics.F1_MACRO: f1_score(y_true, y_pred, average='macro'),
        Metrics.ROC_AUC_MICRO: np.nan,
        Metrics.ROC_AUC_MACRO: np.nan,
        Metrics.RANK_ACCURACY: np.nan,
    }

    # this parameter is most relevant for datasets with high-cardinality
    # labels (lots of poosible values)
    # TODO: make the rank parameter configurable
    results[Metrics.RANK_ACCURACY] = rank_n_accuracy(y_true=y_true,
                                                     y_prob_mat=y_pred_probs)

    # if possible, compute multi-label AUC metrics
    present_classes = np.unique(y_true)
    all_labels_same = len(present_classes) == 1
    any_probs_nan = np.any(np.isnan(y_pred_probs))
    if not (all_labels_same or any_probs_nan):
        # get binary label matrix, ignoring classes that aren't present
        y_true_bin = get_per_class_matrix(y_true)

        # filter out probabilities for classes that aren't in this sample
        filtered_probs = y_pred_probs[:, present_classes]

        # actually compute roc_auc score
        results[Metrics.ROC_AUC_MICRO] = roc_auc_score(y_true_bin,
                                                       filtered_probs,
                                                       average='micro')
        results[Metrics.ROC_AUC_MACRO] = roc_auc_score(y_true_bin,
                                                       filtered_probs,
                                                       average='macro')

    # TODO: multi-label AP metrics?

    # labelwise controls whether to compute separate metrics for each posisble label
    if include_per_class or include_curves:
        results['class_wise'] = {}

        # create binary matrices, including classes that aren't actually present
        all_classes = list(range(y_pred_probs.shape[1]))
        y_true_bin = get_per_class_matrix(y_true, classes=all_classes)
        y_pred_bin = get_per_class_matrix(y_pred, classes=all_classes)

        # for each possible class, generate F1, precision-recall, and ROC scores
        # using the binary metrics function.
        for cls in all_classes:
            class_pred_probs = np.column_stack((1 - y_pred_probs[:, cls],
                                                y_pred_probs[:, cls]))
            class_res = get_metrics_binary(y_true=y_true_bin[:, cls],
                                           y_pred=y_pred_bin[:, cls],
                                           y_pred_probs=class_pred_probs,
                                           include_curves=include_curves)
            results['class_wise'][cls] = class_res

    return results


def test_pipeline(pipeline, X, y, binary, **kwargs):
    if binary:
        get_metrics = get_metrics_binary
    else:
        get_metrics = get_metrics_multiclass

    # run the test data through the trained pipeline
    y_pred = pipeline.predict(X)

    # if necessary (i.e. if a pipeline does not produce probability scores by
    # default), use class distance scores in lieu of probability scores
    method = pipeline.steps[-1][0]
    if method in ['sgd', 'pa']:
        if binary:
            class_1_distance = pipeline.decision_function(X)
            class_0_distance = -class_1_distance
            y_pred_probs = np.column_stack((class_0_distance, class_1_distance))
        else:
            y_pred_probs = pipeline.decision_function(X)
    else:
        y_pred_probs = pipeline.predict_proba(X)

    return get_metrics(y, y_pred, y_pred_probs, **kwargs)


def cross_validate_pipeline(pipeline, X, y, binary=True,
                            n_folds=N_FOLDS_DEFAULT, **kwargs):
    """
    Compute metrics for each of `n_folds` folds of the training data in (X, y).

    pipeline: the sklearn Pipeline to train and test
    X: feature matrix
    y: series of labels corresponding to rows in X
    binary: whether the label is binary or multi-ary
    n_folds: number of non-overlapping "folds" of the data to make for
        cross-validation
    """
    if binary:
        metrics = METRICS_BINARY
    else:
        metrics = METRICS_MULTICLASS

    df = pd.DataFrame(columns=metrics)
    results = []

    # TODO: how to handle classes that are so uncommon that stratified sampling
    # doesn't work? i.e. len([c for c in y if c == some_class]) < n_folds
    skf = StratifiedKFold(n_splits=n_folds)
    skf.get_n_splits(X, y)

    for train_index, test_index in skf.split(X, y):
        pipeline.fit(X[train_index], y[train_index])
        split_results = test_pipeline(pipeline=pipeline,
                                      X=X[test_index],
                                      y=y[test_index],
                                      binary=binary, **kwargs)
        df = df.append([{m: split_results.get(m) for m in metrics}])
        results.append(split_results)

    return df, results
