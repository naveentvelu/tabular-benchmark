import os
os.environ["PROJECT_DIR"] = "test"
from generate_dataset_pipeline import generate_dataset
import traceback  # Needed for pulling out your full stackframe info
from train import *
import wandb
import platform
import time
import torch

#os.environ["WANDB_MODE"] = "offline"


# def modify_config(config):
#     # To overcome wandb limitations on distribution specifications
#     # To match Hyperopt-sklearn
#     dic = {}
#     for key in config.keys():
#         dic[key] = config[key]
#     if config["model_name"] == "xgb_c" or config["model_name"] == "xgb_r":
#         dic["model__learning_rate"] = config["model__learning_rate"] - 0.0001
#         dic["model__gamma"] = config["model__gamma"] - 0.0001
#         dic["model__reg_alpha"] = config["model__reg_alpha"] - 0.0001
#     return dic
def train_model_on_config(config=None):
    print("GPU?")
    print(torch.cuda.device_count())
    print(torch.cuda.is_available())
    #    print(torch.cuda.current_device())
    #    print(torch.cuda.get_device_name(torch.cuda.current_device()))
    print("#####")
    CONFIG_DEFAULT = {"train_prop": 0.70,
                      "val_test_prop": 0.3,
                      "max_val_samples": 50000,
                      "max_test_samples": 50000}
    # "model__use_checkpoints": True} #TODO
    # Initialize a new wandb run
    with wandb.init(config=config) as run:
        run.config.update(CONFIG_DEFAULT)
        config = wandb.config
        print(config)
        # Modify the config in certain cases
        if config["model_name"] == "ft_transformer" or config["model_name"] == "ft_transformer_regressor":
            config["model__module__d_token"] = (config["d_token"] // config["model__module__n_heads"]) * config[
                "model__module__n_heads"]
        # config = modify_config(config)

        # print(config)
        try:
            train_scores = []
            val_scores = []
            test_scores = []
            r2_train_scores = []
            r2_val_scores = []
            r2_test_scores = []
            times = []
            if config["n_iter"] == "auto":
                x_train, x_val, x_test, y_train, y_val, y_test, categorical_indicator = generate_dataset(config, np.random.RandomState(0))
                if x_test.shape[0] > 6000:
                    n_iter = 1
                elif x_test.shape[0] > 3000:
                    n_iter = 2
                elif x_test.shape[0] > 1000:
                    n_iter = 3
                else:
                    n_iter = 5
            else:
                n_iter = config["n_iter"]
            for i in range(n_iter):
                # if config["log_training"]: #FIXME
                #    config["model__wandb_run"] = run
                rng = np.random.RandomState(i)
                print(rng.randn(1))
                # TODO: separate numeric and categorical features
                t = time.time()
                x_train, x_val, x_test, y_train, y_val, y_test, categorical_indicator = generate_dataset(config, rng)
                data_generation_time = time.time() - t
                print("Data generation time:", data_generation_time)
                # print(y_train)
                print(x_train.shape)

                if config["model_type"] == "skorch" and config["regression"]:
                    print("YES")
                    y_train, y_val, y_test = y_train.reshape(-1, 1), y_val.reshape(-1, 1), y_test.reshape(-1, 1)
                    y_train, y_val, y_test = y_train.astype(np.float32), y_val.astype(np.float32), y_test.astype(
                        np.float32)
                else:
                    y_train, y_val, y_test = y_train.reshape(-1), y_val.reshape(-1), y_test.reshape(-1)
                    # y_train, y_val, y_test = y_train.astype(np.float32), y_val.astype(np.float32), y_test.astype(np.float32)
                x_train, x_val, x_test = x_train.astype(np.float32), x_val.astype(np.float32), x_test.astype(
                    np.float32)

                start_time = time.time()
                print(y_train.shape)
                model, model_id = train_model(i, x_train, y_train, categorical_indicator, config)
                if config["regression"]:
                    try:
                        r2_train, r2_val, r2_test = evaluate_model(model, x_train, y_train, x_val, y_val, x_test,
                                                                   y_test, config, model_id, return_r2=True)
                    except:
                        print("R2 score cannot be computed")
                        print(np.any(np.isnan(y_train)))
                        r2_train, r2_val, r2_test = np.nan, np.nan, np.nan
                    r2_train_scores.append(r2_train)
                    r2_val_scores.append(r2_val)
                    r2_test_scores.append(r2_test)
                else:
                    r2_train, r2_val, r2_test = np.nan, np.nan, np.nan
                    r2_train_scores.append(r2_train)
                    r2_val_scores.append(r2_val)
                    r2_test_scores.append(r2_test)
                train_score, val_score, test_score = evaluate_model(model, x_train, y_train, x_val, y_val, x_test,
                                                                    y_test, config, model_id)

                end_time = time.time()
                print("Train score:", train_score)
                print("Val score:", val_score)
                print("Test score:", test_score)
                if config["model_type"] == "skorch":
                    if config["regression"]:
                        if config["transformed_target"]:
                            history = model.regressor_.history
                        else:
                            history = model.history
                        wandb.log({"num_epochs": len(history),
                                   "train_accuracy_vector": [history[i * 10]["train_accuracy"] for i in
                                                             range(len(history) // 10)],
                                   "valid_loss_vector": [history[i * 10]["valid_loss"] for i in
                                                         range(len(history) // 10)]},
                                  commit=False)
                    else:
                        history = model.history
                        wandb.log({"num_epochs": len(history),
                                   "train_accuracy_vector": [history[i * 10]["train_accuracy"] for i in
                                                             range(len(history) // 10)],
                                   "valid_accuracy_vector": [history[i * 10]["valid_acc"] for i in
                                                             range(len(history) // 10)]},
                                  commit=False)

                times.append(end_time - start_time)
                # wandb.log({"train_score": train_score})
                # wandb.log({"test_score": test_score})
                train_scores.append(train_score)
                val_scores.append(val_score)
                test_scores.append(test_score)

            if "model__device" in config.keys():
                if config["model__device"] == "cpu":
                    processor = platform.processor()
                elif config["model__device"] == "cuda":
                    processor = torch.cuda.get_device_name(torch.cuda.current_device())
            else:
                processor = platform.processor()

            if n_iter > 1:
                wandb.log({"train_scores": train_scores,
                           "val_scores": val_scores,
                           "test_scores": test_scores,
                           "mean_train_score": np.mean(train_scores),
                           "mean_val_score": np.mean(val_scores),
                           "mean_test_score": np.mean(test_scores),
                           "std_train_score": np.std(train_scores),
                           "std_val_score": np.std(val_scores),
                           "std_test_score": np.std(test_scores),
                           "max_train_score": np.max(train_scores),
                           "max_val_score": np.max(val_scores),
                           "max_test_score": np.max(test_scores),
                           "min_train_score": np.min(train_scores),
                           "min_val_score": np.min(val_scores),
                           "min_test_score": np.min(test_scores),
                           "mean_r2_train": np.mean(r2_train_scores),
                           "mean_r2_val": np.mean(r2_val_scores),
                           "mean_r2_test": np.mean(r2_test_scores),
                           "std_r2_train": np.std(r2_train_scores),
                           "std_r2_val": np.std(r2_val_scores),
                           "std_r2_test": np.std(r2_test_scores),
                           "mean_time": np.mean(times),
                           "std_time": np.std(times),
                           "times": times,
                           "processor": processor}, commit=False)
            else:
                wandb.log({"mean_train_score": train_score,
                           "mean_val_score": val_score,
                           "mean_test_score": test_score,
                           "mean_r2_train": r2_train,
                           "mean_r2_val": r2_val,
                           "mean_r2_test": r2_test,
                           "mean_time": end_time - start_time,
                           "processor": processor}, commit=False)

            wandb.log({"n_train": x_train.shape[0], "n_test": x_test.shape[0],
                       "n_features": x_train.shape[1],
                       "data_generation_time": data_generation_time})

        except:
            # Print to the console
            print("ERROR")
            # To get the traceback information
            print(traceback.format_exc())
            print(config)
            if config["model_type"] == "skorch" and config["model__use_checkpoints"]:
                print("crashed, trying to remove checkpoint files")
                try:
                    os.remove(r"skorch_cp/params_{}.pt".format(model_id))
                except:
                    print("could not remove params file")
            if config["model_type"] == "tab_survey":
                try:
                    os.remove(r"output/saint/{}/tmp/m_{}_best.pt".format(config["data__keyword"], model_id))
                except:
                    print("could not remove params file")
            return -1
    return 0


if __name__ == """__main__""":
    # config = {"model_type": "sklearn",
    #           "model_name": "rf_c",
    #           "model__n_estimators": 100,
    #           "data__method_name": "real_data",
    #           "data__keyword": "california",
    #           "transform__0__method_name": "add_uninformative_features",
    #           "n_iter": 1,
    #           "max_train_samples": 10000}

    # config = {
    #     "model_type": "skorch",
    #     "model_name": "npt",
    #     "n_iter": 1,
    #     "model__optimizer": "adamw",
    #     "model__lr": 0.001,
    #     "model__batch_size": 64,
    #     "data__method_name": "real_data",
    #     "data__keyword": "electricity",
    #     "regression": False
    # }

    # config = {"model_type": "skorch",
    #           "model_name": "rtdl_resnet",
    #           "n_iter": 1,
    #           "model__device": "cpu",
    #           "model__optimizer": "adam",
    #           "model__lr_scheduler": "adam",
    #           "model__use_checkpoints": True,
    #           "model__batch_size": 64,
    #           "model__max_epochs": 10,
    #           "model__lr": 1e-3,
    #           "model__module__n_layers": 2,
    #           "model__module__d": 64,
    #           "model__module__d_hidden_factor": 3,
    #           "model__module__hidden_dropout": 0.2,
    #           "model__module__residual_dropout": 0.1,
    #           "model__module__d_embedding": 64,
    #           "model__module__normalization": "batchnorm",
    #           "model__module__activation": "reglu",
    #           "data__method_name": "real_data",
    #           "data__keyword": "electricity",
    #           #"max_train_samples": None,
    #           #"max_test_samples": None,
    #           }

    train_model_on_config()
